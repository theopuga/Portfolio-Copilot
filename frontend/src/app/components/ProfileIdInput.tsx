import { useState, useEffect } from 'react';
import { User, Check, X, Edit2 } from 'lucide-react';
import { getUserId, setUserId, onUserIdChange } from '../utils/user';
import { Button } from './ui/button';
import { Input } from './ui/input';

export function ProfileIdInput() {
  const [userId, setUserIdState] = useState<string>('');
  const [isEditing, setIsEditing] = useState(false);
  const [tempUserId, setTempUserId] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Load current user ID on mount
    const currentId = getUserId();
    setUserIdState(currentId);
    setTempUserId(currentId);
    
    // Listen for user ID changes (from other tabs or this component)
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'portfolio_copilot_user_id' && e.newValue) {
        setUserIdState(e.newValue);
        setTempUserId(e.newValue);
      }
    };
    
    // Listen for custom events
    const unsubscribe = onUserIdChange((newUserId) => {
      setUserIdState(newUserId);
      setTempUserId(newUserId);
    });
    
    window.addEventListener('storage', handleStorageChange);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      unsubscribe();
    };
  }, []);

  const handleSave = () => {
    const trimmed = tempUserId.trim();
    if (!trimmed) {
      setError('Profile ID cannot be empty');
      return;
    }
    
    // Validate format (basic check - alphanumeric, underscore, hyphen)
    if (!/^[a-zA-Z0-9_-]+$/.test(trimmed)) {
      setError('Profile ID can only contain letters, numbers, underscores, and hyphens');
      return;
    }

    setError(null);
    setUserId(trimmed);
    setUserIdState(trimmed);
    setIsEditing(false);
  };

  const handleCancel = () => {
    setTempUserId(userId);
    setError(null);
    setIsEditing(false);
  };

  const handleEdit = () => {
    setTempUserId(userId);
    setError(null);
    setIsEditing(true);
  };

  return (
    <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
      <div className="flex items-center gap-2 mb-2">
        <User className="w-4 h-4 text-gray-500" />
        <label className="text-xs font-medium text-gray-700">Profile ID</label>
      </div>
      
      {isEditing ? (
        <div className="space-y-2">
          <Input
            value={tempUserId}
            onChange={(e) => {
              setTempUserId(e.target.value);
              setError(null);
            }}
            placeholder="Enter profile ID"
            className="h-8 text-xs"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                handleSave();
              } else if (e.key === 'Escape') {
                handleCancel();
              }
            }}
            autoFocus
          />
          {error && (
            <p className="text-xs text-red-600">{error}</p>
          )}
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="default"
              onClick={handleSave}
              className="h-6 px-2 text-xs flex-1"
            >
              <Check className="w-3 h-3 mr-1" />
              Save
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleCancel}
              className="h-6 px-2 text-xs flex-1"
            >
              <X className="w-3 h-3 mr-1" />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-mono text-gray-900 truncate" title={userId}>
              {userId}
            </p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleEdit}
            className="h-6 w-6 p-0 ml-2 flex-shrink-0"
            title="Edit Profile ID"
          >
            <Edit2 className="w-3 h-3" />
          </Button>
        </div>
      )}
    </div>
  );
}

