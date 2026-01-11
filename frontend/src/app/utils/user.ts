/**
 * User management utilities
 */

const USER_ID_KEY = 'portfolio_copilot_user_id';

// Event listeners for user ID changes
type UserIdChangeListener = (userId: string) => void;
const listeners: Set<UserIdChangeListener> = new Set();

/**
 * Subscribe to user ID changes
 */
export function onUserIdChange(listener: UserIdChangeListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Notify all listeners of user ID change
 */
function notifyUserIdChange(userId: string): void {
  listeners.forEach(listener => {
    try {
      listener(userId);
    } catch (err) {
      console.error('Error in user ID change listener:', err);
    }
  });
}

/**
 * Get or create a user ID
 * Always returns a valid user ID - never throws or returns empty string
 * 
 * All pages use this same function, so they all refer to the same ID.
 * The ID is stored in localStorage with key 'portfolio_copilot_user_id'.
 */
export function getUserId(): string {
  try {
    let userId = localStorage.getItem(USER_ID_KEY);
    if (!userId || userId.trim() === '') {
      // Generate a simple user ID
      userId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      localStorage.setItem(USER_ID_KEY, userId);
    }
    return userId;
  } catch (err) {
    // If localStorage is disabled/unavailable, generate a session-only ID
    console.warn('localStorage unavailable, using session-only user ID');
    // Reuse existing in-memory ID if present to avoid changing across calls/pages
    const existing = (window as any).__fallback_user_id;
    if (typeof existing === 'string' && existing.trim() !== '') {
      return existing;
    }
    const sessionId = `user_session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    (window as any).__fallback_user_id = sessionId;
    return sessionId;
  }
}

/**
 * Set user ID
 * 
 * This updates the same localStorage key that getUserId() reads from.
 * All pages that call getUserId() will immediately get the new ID.
 * 
 * Also notifies all listeners of the change.
 */
export function setUserId(userId: string): void {
  const trimmed = userId.trim();
  if (!trimmed) {
    throw new Error('User ID cannot be empty');
  }

  // Try to persist to localStorage; if unavailable, keep in-memory fallback
  try {
    localStorage.setItem(USER_ID_KEY, trimmed);
  } catch {
    (window as any).__fallback_user_id = trimmed;
  }
  notifyUserIdChange(trimmed);

  // Best-effort cross-tab sync: only dispatch StorageEvent if localStorage is available
  try {
    if (typeof window !== 'undefined' && typeof localStorage !== 'undefined') {
      window.dispatchEvent(new StorageEvent('storage', {
        key: USER_ID_KEY,
        newValue: trimmed,
        storageArea: localStorage,
      }));
    }
  } catch {
    // Ignore if constructing StorageEvent fails in sandboxed contexts
  }
}

