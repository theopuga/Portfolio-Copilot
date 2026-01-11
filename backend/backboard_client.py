"""Backboard.io client wrapper using official SDK."""

import os
import json
import re
import logging
from datetime import datetime
from typing import Optional, Type, Any
from .models import InvestorProfile

logger = logging.getLogger(__name__)

# Try to import the Backboard SDK - make it optional
try:
    from backboard import BackboardClient as SDKClient
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    SDKClient = None
    logger.warning("backboard SDK not installed. Backboard integration will be disabled. Install with: pip install backboard-sdk")


class BackboardClient:
    """Client for interacting with Backboard.io API using official SDK."""
    
    def __init__(self):
        self.api_key = os.getenv("BACKBOARD_API_KEY", "")
        self.base_url = os.getenv("BACKBOARD_BASE_URL", "https://app.backboard.io/api")
        self.project_id = os.getenv("BACKBOARD_PROJECT_ID", "")
        self.budget_mode = os.getenv("BUDGET_MODE", "false").lower() == "true"
        
        # For demo purposes, if no API key, use in-memory storage
        self._in_memory_storage: dict[str, InvestorProfile] = {}
        self._decision_logs: dict[str, list[str]] = {}
        self._sdk_client: Optional[Any] = None
        self._assistant_id: Optional[str] = None
        
        if not SDK_AVAILABLE:
            logger.warning("Backboard SDK not available. Using in-memory storage only.")
            return
        
        if not self.api_key:
            logger.warning("BACKBOARD_API_KEY not set. Using in-memory storage for demo.")
        else:
            try:
                # Initialize SDK client
                self._sdk_client = SDKClient(api_key=self.api_key, base_url=self.base_url)
                logger.info(f"Backboard SDK client initialized (base_url: {self.base_url})")
            except Exception as e:
                logger.warning(f"Failed to initialize Backboard SDK: {e}")
                logger.warning("Falling back to in-memory storage.")
                self._sdk_client = None
    
    async def _ensure_assistant(self) -> Optional[str]:
        """Ensure we have an assistant for storing memories."""
        if not self._sdk_client:
            return None
        
        if self._assistant_id:
            return self._assistant_id
        
        try:
            # Try to find existing assistant
            assistants = await self._sdk_client.list_assistants()
            for assistant in assistants:
                if assistant.name == "Portfolio Copilot" or "portfolio" in assistant.name.lower():
                    # Assistant ID might be in different attribute
                    assistant_id = getattr(assistant, 'id', None) or getattr(assistant, 'assistant_id', None) or str(assistant)
                    self._assistant_id = str(assistant_id)
                    return self._assistant_id
            
            # Create new assistant if not found
            assistant = await self._sdk_client.create_assistant(
                name="Portfolio Copilot",
                description="Manages investment profiles and portfolio recommendations."
            )
            # Get ID from assistant object
            assistant_id = getattr(assistant, 'id', None) or getattr(assistant, 'assistant_id', None) or str(assistant)
            self._assistant_id = str(assistant_id)
            logger.info(f"Created assistant: {self._assistant_id}")
            return self._assistant_id
        except Exception as e:
            logger.error(f"Error ensuring assistant: {e}", exc_info=True)
            return None
    
    def _get_memory_key(self, user_id: str) -> str:
        """Get memory key for user profile."""
        return f"profile:{user_id}"
    
    def _get_log_key(self, user_id: str) -> str:
        """Get memory key for decision log."""
        return f"log:{user_id}"
    
    def _get_snapshot_key(self, user_id: str, timestamp: str) -> str:
        """Get memory key for portfolio snapshot."""
        return f"portfolio_snapshot:{user_id}:{timestamp}"
    
    def _extract_memories_list(self, memories_response) -> list:
        """Extract list of memories from MemoriesListResponse object."""
        if hasattr(memories_response, 'memories'):
            return memories_response.memories
        elif hasattr(memories_response, 'data'):
            return memories_response.data
        elif hasattr(memories_response, 'items'):
            return memories_response.items
        elif isinstance(memories_response, list):
            return memories_response
        else:
            try:
                return list(memories_response)
            except (TypeError, AttributeError):
                logger.error(f"Unexpected memories response type: {type(memories_response)}, attributes: {dir(memories_response)}")
                return []
    
    async def get_profile(self, user_id: str) -> Optional[InvestorProfile]:
        """Retrieve investor profile from Backboard memory."""
        logger.info(f"Getting profile for user_id: {user_id}")
        
        # ALWAYS try Backboard first if SDK is available (persistent storage)
        # Only use in-memory as fallback
        if self._sdk_client:
            try:
                assistant_id = await self._ensure_assistant()
                if assistant_id:
                    # Get all memories for this assistant
                    logger.debug(f"Fetching memories from Backboard for assistant_id: {assistant_id}")
                    memories_response = await self._sdk_client.get_memories(assistant_id)
                    memories = self._extract_memories_list(memories_response)
                    logger.info(f"Retrieved {len(memories)} memories from Backboard for user_id: {user_id}")
                    
                    # Find memory with matching user_id in metadata
                    memory_key = self._get_memory_key(user_id)
                    logger.debug(f"Looking for profile with memory_key: {memory_key}, user_id: {user_id}")
                    
                    for idx, memory in enumerate(memories):
                        # Handle both object and tuple responses
                        if hasattr(memory, 'metadata'):
                            metadata = memory.metadata or {}
                            content = getattr(memory, 'content', None)
                        elif isinstance(memory, dict):
                            metadata = memory.get('metadata', {})
                            content = memory.get('content')
                        else:
                            metadata = {}
                            content = str(memory) if memory else None
                        
                        # Check both user_id and key matches
                        mem_user_id = metadata.get("user_id") or metadata.get("user_id")
                        mem_key = metadata.get("key")
                        mem_type = metadata.get("type", "")
                        
                        # Debug: log all memories to see what we're getting
                        logger.debug(f"Memory {idx}: user_id={mem_user_id}, key={mem_key}, type={mem_type}, has_content={content is not None}")
                        
                        # Match by user_id, key, or type - be more lenient
                        matches = False
                        if mem_user_id == user_id:
                            matches = True
                            logger.debug(f"Match by user_id: {mem_user_id} == {user_id}")
                        elif mem_key == memory_key:
                            matches = True
                            logger.debug(f"Match by key: {mem_key} == {memory_key}")
                        elif mem_type == "investor_profile":
                            # If type matches, check if user_id also matches
                            if mem_user_id == user_id:
                                matches = True
                                logger.debug(f"Match by type and user_id: {mem_type} + {mem_user_id} == {user_id}")
                        
                        if matches:
                            logger.info(f"Found profile in Backboard memory for user_id: {user_id} (metadata user_id: {mem_user_id}, key: {mem_key}, type: {mem_type})")
                            
                            # Parse profile from memory content
                            if content is None:
                                logger.warning(f"Memory {idx} matched but has no content for user_id: {user_id}")
                                continue
                            
                            # Handle string content
                            if isinstance(content, str):
                                try:
                                    profile_dict = json.loads(content)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse profile JSON for user_id: {user_id}: {e}")
                                    logger.debug(f"Content preview: {content[:500]}")
                                    continue
                            elif isinstance(content, dict):
                                profile_dict = content
                            else:
                                logger.error(f"Unexpected content type for user_id: {user_id}: {type(content)}")
                                continue
                            
                            try:
                                profile = InvestorProfile(**profile_dict)
                                # Verify user_id matches
                                if profile.user_id != user_id:
                                    logger.warning(f"Profile user_id mismatch: expected {user_id}, got {profile.user_id}, updating...")
                                    profile.user_id = user_id
                                
                                # ALWAYS cache in memory for fast access
                                self._in_memory_storage[user_id] = profile
                                logger.info(f"✓ Successfully retrieved and cached profile for user_id: {user_id}")
                                return profile
                            except Exception as e:
                                logger.error(f"Failed to create InvestorProfile from dict for user_id: {user_id}: {e}", exc_info=True)
                                logger.debug(f"Profile dict keys: {list(profile_dict.keys()) if isinstance(profile_dict, dict) else 'N/A'}")
                                continue
                        else:
                            logger.debug(f"Memory {idx} doesn't match: user_id={mem_user_id}, key={mem_key}, type={mem_type}")
                    
                    # Log all memory metadata for debugging
                    logger.warning(f"Profile not found in Backboard memories for user_id: {user_id}, memory_key: {memory_key} (searched {len(memories)} memories)")
                    if memories:
                        logger.warning(f"Available memories metadata:")
                        for idx, mem in enumerate(memories[:10]):  # Log first 10
                            if hasattr(mem, 'metadata'):
                                meta = mem.metadata or {}
                            elif isinstance(mem, dict):
                                meta = mem.get('metadata', {})
                            else:
                                meta = {}
                            logger.warning(f"  Memory {idx}: user_id={meta.get('user_id')}, key={meta.get('key')}, type={meta.get('type')}")
                else:
                    logger.warning(f"Could not get assistant_id, falling back to in-memory for user_id: {user_id}")
            except Exception as e:
                logger.error(f"Error fetching profile from Backboard for user_id {user_id}: {e}", exc_info=True)
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Fallback to in-memory cache
        if user_id in self._in_memory_storage:
            cached_profile = self._in_memory_storage.get(user_id)
            logger.info(f"Profile found in in-memory cache for user_id: {user_id}")
            # If we have SDK but couldn't find in Backboard, log a warning but return cached
            if self._sdk_client:
                logger.warning(f"Profile found in cache but not in Backboard for user_id: {user_id}. This may indicate a sync issue.")
            return cached_profile
        
        logger.error(f"Profile not found anywhere for user_id: {user_id} (checked Backboard and in-memory)")
        logger.error(f"Available user_ids in cache: {list(self._in_memory_storage.keys())}")
        return None
    
    async def set_profile(self, user_id: str, profile: InvestorProfile) -> bool:
        """Store investor profile in Backboard memory."""
        logger.info(f"Storing profile for user_id: {user_id}")
        
        # Always store in in-memory cache first (fast access) - NEVER clear this!
        self._in_memory_storage[user_id] = profile
        logger.info(f"✓ Profile cached in memory for user_id: {user_id} (cache now has {len(self._in_memory_storage)} profiles)")
        
        if not self._sdk_client:
            # No SDK client, only in-memory storage
            logger.warning(f"No SDK client available - profile stored in-memory only for user_id: {user_id}. Profile will be lost on server restart!")
            return True
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                logger.warning(f"Could not get assistant_id - profile stored in-memory only for user_id: {user_id}. Profile will be lost on server restart!")
                return True
            
            memory_key = self._get_memory_key(user_id)
            profile_json = json.dumps(profile.model_dump(), indent=2)
            logger.debug(f"Storing profile to Backboard with memory_key: {memory_key}")
            
            # Check if memory already exists
            memories_response = await self._sdk_client.get_memories(assistant_id)
            memories = self._extract_memories_list(memories_response)
            existing_memory_id = None
            for memory in memories:
                # Handle both object and tuple responses
                if hasattr(memory, 'metadata'):
                    metadata = memory.metadata or {}
                    mem_id = getattr(memory, 'id', None) or getattr(memory, 'memory_id', None)
                elif isinstance(memory, dict):
                    metadata = memory.get('metadata', {})
                    mem_id = memory.get('id') or memory.get('memory_id')
                else:
                    metadata = {}
                    mem_id = None
                    
                if metadata.get("user_id") == user_id or metadata.get("key") == memory_key:
                    existing_memory_id = str(mem_id) if mem_id else None
                    logger.debug(f"Found existing memory for user_id: {user_id}, memory_id: {existing_memory_id}")
                    break
            
            metadata = {
                "user_id": user_id,
                "key": memory_key,
                "type": "investor_profile",
                "last_updated": datetime.utcnow().isoformat()
            }
            
            if existing_memory_id:
                # Update existing memory
                logger.info(f"Updating existing profile memory for user_id: {user_id}, memory_id: {existing_memory_id}")
                await self._sdk_client.update_memory(
                    assistant_id=assistant_id,
                    memory_id=existing_memory_id,
                    content=profile_json,
                    metadata=metadata
                )
            else:
                # Create new memory
                logger.info(f"Creating new profile memory for user_id: {user_id}")
                result = await self._sdk_client.add_memory(
                    assistant_id=assistant_id,
                    content=profile_json,
                    metadata=metadata
                )
                logger.debug(f"add_memory result: {result}")
            
            # Verify the profile was saved by trying to retrieve it
            logger.info(f"Verifying profile was saved to Backboard for user_id: {user_id}")
            verify_profile = await self.get_profile(user_id)
            if verify_profile and verify_profile.user_id == user_id:
                logger.info(f"✓ Profile successfully persisted to Backboard for user_id: {user_id}")
            else:
                logger.error(f"✗ Profile verification failed for user_id: {user_id} - profile may not be persisted!")
            
            return True
        except Exception as e:
            logger.error(f"Error storing profile to Backboard for user_id {user_id}: {e}", exc_info=True)
            # Profile is already in in-memory storage, so we can still return True
            logger.warning(f"Profile remains available in-memory only for user_id: {user_id} - will be lost on server restart!")
            return True
    
    async def append_decision(self, user_id: str, entry: str) -> bool:
        """Append entry to decision log."""
        if not self._sdk_client:
            # In-memory fallback
            if user_id not in self._decision_logs:
                self._decision_logs[user_id] = []
            self._decision_logs[user_id].append(entry)
            return True
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                if user_id not in self._decision_logs:
                    self._decision_logs[user_id] = []
                self._decision_logs[user_id].append(entry)
                return True
            
            log_key = self._get_log_key(user_id)
            
            # Get existing log or create new
            memories_response = await self._sdk_client.get_memories(assistant_id)
            memories = self._extract_memories_list(memories_response)
            existing_log_id = None
            log_content = ""
            for memory in memories:
                # Handle both object and tuple responses (same as in get_profile)
                if hasattr(memory, 'metadata'):
                    metadata = memory.metadata or {}
                    mem_id = getattr(memory, 'id', None) or getattr(memory, 'memory_id', None)
                    mem_content = getattr(memory, 'content', '') if hasattr(memory, 'content') else ''
                elif isinstance(memory, dict):
                    metadata = memory.get('metadata', {})
                    mem_id = memory.get('id') or memory.get('memory_id')
                    mem_content = memory.get('content', '')
                else:
                    metadata = {}
                    mem_id = None
                    mem_content = ''
                
                if metadata.get("key") == log_key:
                    existing_log_id = str(mem_id) if mem_id else None
                    log_content = mem_content
                    break
            
            # Append new entry
            timestamp = datetime.utcnow().isoformat()
            new_entry = f"[{timestamp}] {entry}\n"
            updated_log = log_content + new_entry
            
            metadata = {
                "user_id": user_id,
                "key": log_key,
                "type": "decision_log"
            }
            
            if existing_log_id:
                await self._sdk_client.update_memory(
                    assistant_id=assistant_id,
                    memory_id=existing_log_id,
                    content=updated_log,
                    metadata=metadata
                )
            else:
                await self._sdk_client.add_memory(
                    assistant_id=assistant_id,
                    content=new_entry,
                    metadata=metadata
                )
            
            return True
        except Exception as e:
            logger.error(f"Error appending to log: {e}", exc_info=True)
            # Fallback to in-memory
            if user_id not in self._decision_logs:
                self._decision_logs[user_id] = []
            self._decision_logs[user_id].append(entry)
            return True
    
    async def append_memory(self, user_id: str, key: str, content: dict) -> bool:
        """Append a memory entry to Backboard.io memory."""
        if not self._sdk_client:
            # In-memory fallback - store in a simple dict
            if not hasattr(self, '_memory_storage'):
                self._memory_storage: dict[str, list] = {}
            if user_id not in self._memory_storage:
                self._memory_storage[user_id] = []
            self._memory_storage[user_id].append({
                'key': key,
                'content': content,
                'timestamp': datetime.utcnow().isoformat()
            })
            return True
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                # Fallback to in-memory
                if not hasattr(self, '_memory_storage'):
                    self._memory_storage: dict[str, list] = {}
                if user_id not in self._memory_storage:
                    self._memory_storage[user_id] = []
                self._memory_storage[user_id].append({
                    'key': key,
                    'content': content,
                    'timestamp': datetime.utcnow().isoformat()
                })
                return True
            
            memory_key = key
            content_json = json.dumps(content, indent=2)
            
            metadata = {
                "user_id": user_id,
                "key": memory_key,
                "type": "portfolio_snapshot",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Create new memory entry
            await self._sdk_client.add_memory(
                assistant_id=assistant_id,
                content=content_json,
                metadata=metadata
            )
            
            # Also store in in-memory fallback for reliability
            if not hasattr(self, '_memory_storage'):
                self._memory_storage: dict[str, list] = {}
            if user_id not in self._memory_storage:
                self._memory_storage[user_id] = []
            self._memory_storage[user_id].append({
                'key': memory_key,
                'content': content,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            return True
        except Exception as e:
            logger.error(f"Error storing memory to Backboard: {e}", exc_info=True)
            # Fallback to in-memory storage
            if not hasattr(self, '_memory_storage'):
                self._memory_storage: dict[str, list] = {}
            if user_id not in self._memory_storage:
                self._memory_storage[user_id] = []
            self._memory_storage[user_id].append({
                'key': key,
                'content': content,
                'timestamp': datetime.utcnow().isoformat()
            })
            return True
    
    async def get_memories(self, user_id: str, key_prefix: Optional[str] = None) -> list:
        """Retrieve memories for a user, optionally filtered by key prefix."""
        if not self._sdk_client:
            # In-memory fallback
            if not hasattr(self, '_memory_storage'):
                return []
            memories = self._memory_storage.get(user_id, [])
            if key_prefix:
                memories = [m for m in memories if m.get('key', '').startswith(key_prefix)]
            return memories
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                # Fallback to in-memory
                if not hasattr(self, '_memory_storage'):
                    return []
                memories = self._memory_storage.get(user_id, [])
                if key_prefix:
                    memories = [m for m in memories if m.get('key', '').startswith(key_prefix)]
                return memories
            
            # Get all memories for this assistant
            try:
                memories_response = await self._sdk_client.get_memories(assistant_id)
                memories = self._extract_memories_list(memories_response)
            except Exception as e:
                logger.warning(f"Error getting memories from Backboard SDK: {e}, using in-memory fallback")
                memories = []
            
            # Also check in-memory storage as fallback
            in_memory_fallback = []
            if hasattr(self, '_memory_storage'):
                in_memory_fallback = self._memory_storage.get(user_id, [])
                if key_prefix:
                    in_memory_fallback = [m for m in in_memory_fallback if m.get('key', '').startswith(key_prefix)]
            
            # Filter by user_id and optionally by key prefix
            filtered_memories = []
            for memory in memories:
                # Handle both object and tuple responses
                if hasattr(memory, 'metadata'):
                    metadata = memory.metadata or {}
                elif isinstance(memory, dict):
                    metadata = memory.get('metadata', {})
                else:
                    metadata = {}
                
                # Check if this memory belongs to the user
                if metadata.get("user_id") == user_id:
                    # Check key prefix if specified
                    memory_key = metadata.get("key", "")
                    if key_prefix and not memory_key.startswith(key_prefix):
                        continue
                    
                    # Extract content
                    content = None
                    if hasattr(memory, 'content'):
                        content = memory.content
                    elif isinstance(memory, dict):
                        content = memory.get('content', '')
                    
                    # Parse JSON content
                    try:
                        if isinstance(content, str):
                            content_dict = json.loads(content)
                        else:
                            content_dict = content
                        
                        # Create a simple dict representation
                        filtered_memories.append({
                            'key': memory_key,
                            'content': content_dict,
                            'timestamp': metadata.get('timestamp', datetime.utcnow().isoformat())
                        })
                    except (json.JSONDecodeError, TypeError):
                        # If content is not JSON, use as-is
                        filtered_memories.append({
                            'key': memory_key,
                            'content': content,
                            'timestamp': metadata.get('timestamp', datetime.utcnow().isoformat())
                        })
            
            # Merge with in-memory fallback (avoid duplicates)
            seen_keys = {m['key'] for m in filtered_memories}
            for mem in in_memory_fallback:
                if mem.get('key') not in seen_keys:
                    filtered_memories.append(mem)
                    seen_keys.add(mem.get('key'))
            
            return filtered_memories
        except Exception as e:
            logger.error(f"Error fetching memories from Backboard: {e}", exc_info=True)
            # Fallback to in-memory
            if not hasattr(self, '_memory_storage'):
                return []
            memories = self._memory_storage.get(user_id, [])
            if key_prefix:
                memories = [m for m in memories if m.get('key', '').startswith(key_prefix)]
            return memories
    
    async def cheap_extract_profile(self, onboarding_text: str) -> InvestorProfile:
        """Use CHEAP model to extract InvestorProfile from onboarding text."""
        logger.error("=" * 100)
        logger.error(f"🚀 cheap_extract_profile CALLED - text length: {len(onboarding_text)}")
        logger.error(f"📝 First 200 chars: {onboarding_text[:200]}")
        logger.error("=" * 100)
        
        if not self._sdk_client:
            # Fallback: parse basic keywords for demo
            logger.error("❌ No SDK client, using fallback parser")
            return self._parse_profile_fallback(onboarding_text)
        
        logger.error("✅ SDK client exists, proceeding with Backboard API")
        
        try:
            logger.error("🔍 Checking assistant...")
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                logger.error("❌ No assistant ID, using fallback parser")
                return self._parse_profile_fallback(onboarding_text)
            logger.error(f"✅ Assistant ID: {assistant_id}")
            
            # Load sector data for context
            from .sector_data import get_sectors_by_keywords, load_sectors_data
            
            # Load sector aliases for AI reference
            import json as json_module
            from pathlib import Path
            aliases_file = Path(__file__).parent.parent / "data" / "sector_aliases.json"
            with open(aliases_file, 'r') as f:
                aliases_data = json_module.load(f)
            
            # Build comprehensive alias mapping for AI
            alias_mapping_text = ""
            for sector_name, sector_info in aliases_data['sector_aliases'].items():
                aliases = ", ".join(sector_info['aliases'][:10])  # Show first 10 aliases
                alias_mapping_text += f"- {sector_info['exact_name']}: {aliases}\n"
            
            system_prompt = f"""You are an investment profile analyzer. Extract investor preferences and map them to exact sector names.

SECTOR ALIAS MAPPING (map user keywords to these EXACT sector names):
{alias_mapping_text}

CRITICAL INSTRUCTIONS:
1. Analyze the user's text for sector interests
2. Match any mentioned keywords/aliases to the EXACT sector names above
3. For sectors_like and sectors_avoid, use ONLY the exact_name values (e.g., "Healthcare", "Technology", NOT "biotech" or "tech")
4. Map all variations: "biotech" → "Healthcare", "tech" → "Technology", "banks" → "Financial Services", etc.

HORIZON EXTRACTION RULES (CRITICAL - convert to horizon_months as INTEGER):
- If user says "X years" or "X year" where X is a number: horizon_months = X * 12
  Examples: "3 years" → 36, "5 years" → 60, "10 years" → 120, "15 years" → 180, "20 years" → 240
- If user says "X months" or "X month" where X is a number: horizon_months = X
  Examples: "18 months" → 18, "24 months" → 24, "6 months" → 6
- "long horizon", "long term", "long-term" → 60-120 months (use 60 as default)
- "short horizon", "short term", "short-term" → 6-24 months (use 12 as default)
- "early investor", "early stage" → 60-120 months (use 72 as default)
- "retirement", "retire" → 120-240 months (use 180 as default)
- If user says "retirement in X years": horizon_months = X * 12 (e.g., "retirement in 10 years" → 120)
- If no horizon mentioned: default to 60 months

CRITICAL: Always prioritize explicit numbers (years/months) over keywords. If user says "3 years", use 36 months, NOT 60.

RISK SCORE EXTRACTION RULES (0-100 scale, use INTEGER):
- "risk averse", "I'm risk averse", "very conservative", "low risk" → 20-30 (use 25)
- "conservative", "somewhat conservative" → 20-30 (use 25)
- "moderate risk", "moderate", "balanced" → 40-50 (use 50)
- "aggressive", "high risk", "risk tolerant", "I'm aggressive" → 70-80 (use 75)
- "very aggressive", "very high risk" → 80-90 (use 85)
- If no risk mentioned: default to 50

CRITICAL: If user explicitly says "risk averse" or "I'm risk averse", use 20-30, NOT 50.

OBJECTIVE EXTRACTION:
- "growth", "capital appreciation", "growth focus", "looking for growth" → "growth"
- "income", "dividend", "yield", "need income", "want income" → "income"
- "balanced", "both", "balanced approach" → "balanced"
- If unclear: default to "balanced"

CONSTRAINTS EXTRACTION:
- "max X holdings" or "maximum X holdings" → constraints.max_holdings = X (integer)
- "max X% per position" or "no position exceed X%" → constraints.max_position_pct = X (float)
- "avoid X" or "don't want X" → preferences.sectors_avoid should include X (mapped to exact sector name)
- "exclude X" → preferences.sectors_avoid should include X (mapped to exact sector name)

REBALANCE FREQUENCY:
- "monthly" or "rebalance monthly" → "monthly"
- "quarterly" or "rebalance quarterly" → "quarterly"
- "annual" or "yearly" or "rebalance annually" → "annual"
- If not mentioned: default to "quarterly"

Return ONLY valid JSON matching InvestorProfile schema. No prose, no explanation, just valid JSON.
            
InvestorProfile schema:
{{
  "user_id": "string",
  "objective": {{"type": "growth"|"income"|"balanced", "notes": "string"}},
  "horizon_months": int,
  "risk_score": int (0-100),
  "constraints": {{
    "max_holdings": int,
    "max_position_pct": float,
    "exclusions": list[str],
    "options_allowed": bool,
    "leverage_allowed": bool
  }},
  "preferences": {{
    "sectors_like": list[str],  // MUST use exact sector names from the list above
    "sectors_avoid": list[str],  // MUST use exact sector names from the list above
    "regions_like": list[str]
  }},
  "rebalance_frequency": "monthly"|"quarterly"|"annual",
  "last_updated": "ISO datetime string"
}}

CRITICAL: 
- For sectors_like and sectors_avoid, you MUST use the exact sector names from the list above (e.g., "Healthcare", "Technology", NOT generic keywords).
- Extract horizon_months carefully using the rules above.
- Extract risk_score using the rules above.
- Return ONLY valid JSON, no markdown, no code blocks, just the JSON object."""
            
            # Use Backboard assistant to extract profile via AI
            # Create a thread and send message with system prompt
            logger.error("🔄 Creating thread...")
            try:
                thread = await self._sdk_client.create_thread(assistant_id=assistant_id)
                logger.error(f"✅ Thread created: {type(thread)}")
            except Exception as thread_error:
                logger.error(f"❌ Failed to create thread: {thread_error}")
                raise
            
            # Get thread ID correctly (same as in ticker_lookup.py)
            thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
            logger.error(f"📋 Thread ID: {thread_id}")
            
            # Combine system prompt with user text
            full_prompt = f"{system_prompt}\n\nUser onboarding text:\n{onboarding_text}"
            
            # Log input lengths for debugging
            logger.error(f"📏 Profile extraction - onboarding_text length: {len(onboarding_text)}, full_prompt length: {len(full_prompt)}")
            
            # Send message - this triggers the assistant and returns AI response
            response = None
            response_text = None
            
            # Try calling add_message - ALWAYS use supported models first (not assistant default which uses unsupported gpt-4o-mini)
            # This matches ticker_lookup.py strategy (lines 656-723)
            response = None
            raw_response_data = None
            
            # Use standard OpenAI models that work with Backboard API
            # Use gpt-4o-mini for cheap operations (fast, cost-effective)
            supported_models = [
                "gpt-4o-mini",  # Standard cheap model - should work
                "gpt-4o",       # Fallback if mini not available
            ]
            
            logger.error("=" * 100)
            logger.error("🔍 DEBUGGING BACKBOARD API CALL - Starting add_message attempts...")
            logger.error(f"   Thread ID: {thread_id}")
            logger.error(f"   Prompt length: {len(full_prompt)}")
            logger.error(f"   Will try {len(supported_models)} supported models")
            logger.error("=" * 100)
            
            # Strategy: Try without model first (assistant default), then try explicit models
            model_attempted = False
            last_exception = None
            
            # First, try without specifying a model (use assistant's default)
            try:
                logger.error("📤 Attempt 1: Trying without model (assistant default)...")
                response = await self._sdk_client.add_message(
                    thread_id=thread_id,
                    content=full_prompt
                )
                logger.error(f"✅ Assistant default model worked! Response type: {type(response)}")
                model_attempted = True
            except Exception as default_error:
                error_str = str(default_error).lower()
                error_type = type(default_error).__name__
                logger.error(f"❌ Assistant default failed: {error_type}")
                logger.error(f"   Error message: {str(default_error)[:300]}")
                
                # Check if it's a validation error (message was sent, just parsing failed)
                if "validation" in error_str and "field required" in error_str:
                    logger.error(f"   → Validation error (message was sent), will extract from thread messages...")
                    # Will extract from thread messages below
                    model_attempted = True
                else:
                    last_exception = default_error
                    # Try explicit models as fallback
                    for model_idx, supported_model in enumerate(supported_models, 1):
                        try:
                            logger.error(f"📤 Attempt {model_idx + 1}: Trying model '{supported_model}'...")
                            response = await self._sdk_client.add_message(
                                thread_id=thread_id,
                                content=full_prompt,
                                llm_provider="openai",
                                model_name=supported_model
                            )
                            logger.error(f"✅ SUCCESS! Model '{supported_model}' worked! Response type: {type(response)}")
                            model_attempted = True
                            break
                        except Exception as model_error:
                            error_str = str(model_error).lower()
                            logger.error(f"❌ Model '{supported_model}' failed: {str(model_error)[:200]}")
                            last_exception = model_error
                            continue
            
            # If we got a response object, try to extract content from it
            if response:
                try:
                    # If no model fails, try with supported models (like ticker_lookup.py lines 679-720)
                    logger.error(f"🔍 Checking response object for content...")
                    # Try to extract response from the response object first (like ticker_lookup.py does)
                    if hasattr(response, 'content'):
                        response_text = response.content
                        logger.error(f"✅ Found response.content: {type(response_text)}, length: {len(response_text) if response_text else 0}")
                    elif hasattr(response, 'latest_message'):
                        if hasattr(response.latest_message, 'content'):
                            response_text = response.latest_message.content
                            logger.error(f"✅ Found response.latest_message.content: {type(response_text)}, length: {len(response_text) if response_text else 0}")
                        elif isinstance(response.latest_message, dict):
                            response_text = response.latest_message.get('content', '')
                            logger.error(f"✅ Found response.latest_message dict content: length: {len(response_text) if response_text else 0}")
                    elif hasattr(response, 'message'):
                        if hasattr(response.message, 'content'):
                            response_text = response.message.content
                            logger.error(f"✅ Found response.message.content: {type(response_text)}, length: {len(response_text) if response_text else 0}")
                        elif isinstance(response.message, dict):
                            response_text = response.message.get('content', '')
                            logger.error(f"✅ Found response.message dict content: length: {len(response_text) if response_text else 0}")
                    elif isinstance(response, dict):
                        response_text = (
                            response.get('latest_message', {}).get('content', '') or
                            response.get('message', {}).get('content', '') or
                            response.get('content', '') or
                            ''
                        )
                        logger.error(f"✅ Found response dict content: length: {len(response_text) if response_text else 0}")
                    else:
                        logger.error(f"⚠️  Response object doesn't have expected attributes: {dir(response)[:20]}")
                except Exception as extract_err:
                    logger.error(f"⚠️  Error extracting response from response object: {extract_err}")
            else:
                logger.error(f"⚠️  No response object to extract from")
            
            # If we still don't have response_text and got a validation error, the message was sent
            # We need to wait and fetch from thread messages
            if not response_text or len(response_text.strip()) < 10:
                if last_exception:
                    error_msg = str(last_exception)
                    error_type = type(last_exception).__name__
                    logger.error("=" * 100)
                    logger.error("🔍 DEBUGGING: No response_text yet, analyzing exception...")
                    logger.error(f"   Last exception type: {error_type}")
                    logger.error(f"   Last exception message: {error_msg[:500]}")
                    logger.error(f"   Has input_value: {hasattr(last_exception, 'input_value')}")
                    if hasattr(last_exception, 'input_value'):
                        try:
                            logger.error(f"   input_value type: {type(last_exception.input_value)}")
                            if isinstance(last_exception.input_value, dict):
                                logger.error(f"   input_value keys: {list(last_exception.input_value.keys())[:20]}")
                                if 'content' in last_exception.input_value:
                                    content = last_exception.input_value['content']
                                    logger.error(f"   Found 'content' in input_value: {type(content)}, length: {len(str(content)) if content else 0}")
                                    logger.error(f"   Content preview: {str(content)[:300]}")
                        except Exception as debug_err:
                            logger.error(f"   Error inspecting input_value: {debug_err}")
                    logger.error("=" * 100)
                    
                    # Also try to extract raw_response_data from exception if we haven't already
                    if not raw_response_data:
                        try:
                            if hasattr(last_exception, 'input_value'):
                                raw_response_data = last_exception.input_value
                                logger.error(f"✅ Extracted raw_response_data from exception.input_value: {type(raw_response_data)}")
                            elif hasattr(last_exception, 'errors') and callable(last_exception.errors):
                                errors = last_exception.errors()
                                if errors and len(errors) > 0:
                                    first_error = errors[0]
                                    if 'input' in first_error:
                                        raw_response_data = first_error['input']
                                        logger.error(f"✅ Extracted raw_response_data from exception.errors: {type(raw_response_data)}")
                        except Exception as extract_error:
                            logger.error(f"⚠️  Could not extract from exception attributes: {extract_error}")
                
                # Extract response_text from raw_response_data
                if raw_response_data:
                    logger.error(f"🔍 Processing raw_response_data (type: {type(raw_response_data)}): {str(raw_response_data)[:500]}")
                    if isinstance(raw_response_data, dict):
                        # The API returns 'message' but SDK expects 'latest_message'
                        # First check if there's a 'message' field (which is what the error shows)
                        if 'message' in raw_response_data:
                            message_obj = raw_response_data['message']
                            logger.error(f"   Found 'message' key: {type(message_obj)}")
                            if isinstance(message_obj, dict):
                                # Try to get content from message dict
                                response_text = (
                                    message_obj.get('content', '') or
                                    message_obj.get('text', '') or
                                    str(message_obj)
                                )
                                logger.error(f"   Extracted from message dict: length: {len(response_text) if response_text else 0}")
                            elif isinstance(message_obj, str):
                                # Message is already a string
                                response_text = message_obj
                                logger.error(f"   Message is string: length: {len(response_text) if response_text else 0}")
                            else:
                                # Try to get content attribute from message object
                                if hasattr(message_obj, 'content'):
                                    response_text = message_obj.content
                                    logger.error(f"   Found message.content: length: {len(response_text) if response_text else 0}")
                                else:
                                    response_text = str(message_obj)
                                    logger.error(f"   Converted message to string: length: {len(response_text) if response_text else 0}")
                        else:
                            # Try other keys
                            response_text = (
                                raw_response_data.get('latest_message', {}).get('content', '') if isinstance(raw_response_data.get('latest_message'), dict) else '' or
                                raw_response_data.get('content', '') or
                                raw_response_data.get('text', '') or
                                ''
                            )
                            logger.error(f"   Extracted from other keys: length: {len(response_text) if response_text else 0}")
                        
                        if response_text and len(response_text) > 50:
                            logger.error(f"✅ Got valid response from exception! First 200 chars: {response_text[:200]}")
                        else:
                            logger.error(f"⚠️  Response from exception too short, will try thread messages")
                            response_text = None  # Will try thread messages instead
                
                # Try to extract from exception args as fallback (if we still don't have response_text)
                if not response_text and last_exception and hasattr(last_exception, 'args') and len(last_exception.args) > 0:
                    logger.error("   Trying to extract from exception args...")
                    for arg in last_exception.args:
                        if isinstance(arg, dict):
                            response_text = (
                                arg.get('latest_message', {}).get('content', '') or
                                arg.get('message', {}).get('content', '') or
                                arg.get('content', '') or
                                ''
                            )
                            if response_text and len(response_text) > 50:
                                logger.error(f"✅ Got valid response from exception args! Length: {len(response_text)}")
                                break
                
                # Check if error mentions content length or truncation (only if we have last_exception and error_msg)
                if not response_text and last_exception:
                    error_msg = str(last_exception)
                    if ("length" in error_msg.lower() or "too long" in error_msg.lower() or "truncat" in error_msg.lower() or "max" in error_msg.lower()):
                        logger.error(f"Content length issue detected! Full error: {error_msg[:300]}")
                        # Try to send just the user text with a shorter system prompt
                        short_system = "Extract investor profile from the following text. Return ONLY valid JSON matching InvestorProfile schema."
                        short_prompt = f"{short_system}\n\n{onboarding_text}"
                        logger.info(f"Retrying with shorter prompt (length: {len(short_prompt)})")
                        try:
                            response = await self._sdk_client.add_message(
                                thread_id=thread_id,
                                content=short_prompt,
                                llm_provider="openai",
                                model_name="gpt-4o-mini"
                            )
                            logger.info("Successfully sent shortened message")
                            # Try to extract from retry response too
                            if response and hasattr(response, 'content'):
                                response_text = response.content
                        except Exception as retry_error:
                            logger.error(f"Retry with shortened prompt also failed: {retry_error}")
                
                import asyncio
                
                # If we still don't have response_text, wait and fetch from thread messages
                if not response_text or len(response_text.strip()) < 10:
                    # Wait for AI to process (validation error means message was sent)
                    # Wait longer for the AI to generate a response - AI needs more time for profile extraction
                    logger.error("⏳ No response from add_message, waiting 12 seconds for AI to respond...")
                    await asyncio.sleep(12)  # Increased to 12 seconds - profile extraction takes longer
                    
                    # Try to get messages from thread
                    try:
                        logger.error("📥 Fetching messages from thread...")
                        messages = None
                        if hasattr(self._sdk_client, 'get_messages'):
                            logger.error("Using get_messages() method")
                            messages = await self._sdk_client.get_messages(thread_id=thread_id)
                        elif hasattr(self._sdk_client, 'list_messages'):
                            logger.error("Using list_messages() method")
                            messages = await self._sdk_client.list_messages(thread_id=thread_id)
                        elif hasattr(self._sdk_client, 'get_thread'):
                            logger.error("Using get_thread() method")
                            thread_obj = await self._sdk_client.get_thread(thread_id=thread_id)
                            if hasattr(thread_obj, 'messages'):
                                messages = thread_obj.messages
                        else:
                            logger.error("❌ No method to get messages found!")
                        
                        logger.error(f"📨 Messages retrieved: {type(messages)}, length: {len(messages) if messages else 0}")
                        logger.error(f"📨 Messages truthy check: {bool(messages)}")
                        
                        # DEBUG: Log full message structure to understand what we're getting
                        if messages and isinstance(messages, list) and len(messages) > 0:
                            logger.error(f"🔍 DEBUG: First message type: {type(messages[0])}")
                            logger.error(f"🔍 DEBUG: First message dir (first 20): {dir(messages[0])[:20] if hasattr(messages[0], '__dict__') else 'N/A'}")
                            if isinstance(messages[0], dict):
                                logger.error(f"🔍 DEBUG: First message keys: {list(messages[0].keys())[:15]}")
                            elif hasattr(messages[0], '__dict__'):
                                logger.error(f"🔍 DEBUG: First message attributes: {list(messages[0].__dict__.keys())[:15]}")
                        
                        if messages:
                            try:
                                logger.error(f"✅ Entering messages processing block...")
                                # Handle different message formats (matching ticker_lookup.py exactly)
                                msg_list = []
                                if isinstance(messages, list):
                                    msg_list = messages
                                    logger.error(f"   Messages is a list with {len(msg_list)} items")
                                elif hasattr(messages, 'messages'):
                                    msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                                    logger.error(f"   Messages has .messages attribute: {len(msg_list)} items")
                                else:
                                    logger.error(f"   Messages format unexpected: {type(messages)}, dir: {dir(messages)[:10]}")
                                    msg_list = []
                                
                                logger.error(f"   Processing {len(msg_list)} messages...")
                                
                                # Find the latest assistant message (matching ticker_lookup.py line 790-812)
                                for idx, msg in enumerate(reversed(msg_list)):
                                    logger.error(f"   Message {idx}: type={type(msg)}")
                                    if isinstance(msg, dict):
                                        logger.error(f"      Dict keys: {list(msg.keys())[:10]}")
                                        logger.error(f"      Has 'content': {'content' in msg}")
                                        logger.error(f"      Has 'role': {'role' in msg}")
                                        if 'content' in msg:
                                            logger.error(f"      Content type: {type(msg['content'])}, length: {len(str(msg['content'])) if msg['content'] else 0}")
                                    
                                    is_assistant = False
                                    role_str = None
                                    if hasattr(msg, 'role'):
                                        role = msg.role
                                        # Convert role to string for checking - handle MessageRole enum
                                        if hasattr(role, 'value'):
                                            role_str = str(role.value).lower()
                                            role_upper = str(role.value).upper()
                                        elif hasattr(role, 'name'):
                                            role_str = str(role.name).lower()
                                            role_upper = str(role.name).upper()
                                        else:
                                            # Check the string representation (might be "MessageRole.USER" or "MessageRole.ASSISTANT")
                                            role_str_full = str(role)
                                            role_str = role_str_full.lower()
                                            role_upper = role_str_full.upper()
                                        
                                        # CRITICAL: Explicitly check for USER first - MessageRole.USER is NEVER assistant!
                                        # MessageRole.USER -> value="user" or "MessageRole.USER" -> NOT assistant
                                        # MessageRole.ASSISTANT -> value="assistant" or "MessageRole.ASSISTANT" -> IS assistant
                                        # Check exact value first, then string representation
                                        role_value_exact = None
                                        if hasattr(role, 'value'):
                                            role_value_exact = str(role.value).lower()
                                        elif hasattr(role, 'name'):
                                            role_value_exact = str(role.name).lower()
                                        
                                        if role_value_exact == 'user':
                                            is_assistant = False
                                        elif role_value_exact in ['assistant', 'ai', 'bot']:
                                            is_assistant = True
                                        elif 'user' in role_str and role_str != 'assistant' and 'assistant' not in role_str:
                                            # String contains "user" but not "assistant" -> USER
                                            is_assistant = False
                                        elif 'assistant' in role_str or 'ai' in role_str or 'bot' in role_str:
                                            # String contains "assistant" -> ASSISTANT
                                            is_assistant = True
                                        else:
                                            # Default to False if we can't determine (safer)
                                            is_assistant = False
                                        
                                        logger.error(f"      Role from attr: {role} (value: '{role_value_exact}', full string: '{str(role)}', parsed: '{role_str}'), is_assistant: {is_assistant}")
                                    elif isinstance(msg, dict):
                                        # Check both 'role' and 'type' keys (like ticker_lookup.py line 796)
                                        role_val = msg.get('role', '')
                                        type_val = msg.get('type', '')
                                        role_str = str(role_val).lower() if role_val else ''
                                        type_str = str(type_val).lower() if type_val else ''
                                        
                                        # CRITICAL: Explicitly check for USER - if it contains "user", it's NOT assistant!
                                        if ('user' in role_str or 'user' in type_str) and 'assistant' not in role_str and 'assistant' not in type_str:
                                            is_assistant = False
                                        elif 'assistant' in role_str or 'assistant' in type_str or 'ai' in role_str or 'bot' in role_str:
                                            is_assistant = True
                                        else:
                                            is_assistant = False
                                        
                                        logger.error(f"      Role from dict: '{role_val}' (lower: '{role_str}'), type: '{type_val}' (lower: '{type_str}'), is_assistant: {is_assistant}")
                                    
                                    # Extract content (matching ticker_lookup.py line 798-803 exactly)
                                    content = None
                                    if hasattr(msg, 'content'):
                                        content = msg.content
                                        logger.error(f"      Content from attr: {type(content)}, length: {len(content) if content else 0}")
                                    elif isinstance(msg, dict) and 'content' in msg:  # Check key exists first
                                        content = msg['content']
                                        logger.error(f"      Content from dict key: {type(content)}, length: {len(content) if content else 0}")
                                    
                                    if content:
                                        # Convert to string if needed
                                        if not isinstance(content, str):
                                            logger.error(f"      🔄 Converting content from {type(content)} to string...")
                                            try:
                                                # Try to extract text from object
                                                if hasattr(content, 'text'):
                                                    content = content.text
                                                    logger.error(f"         → Extracted from .text attribute")
                                                elif hasattr(content, 'body'):
                                                    content = content.body
                                                    logger.error(f"         → Extracted from .body attribute")
                                                elif isinstance(content, (list, tuple)) and len(content) > 0:
                                                    # Content might be a list of text parts
                                                    logger.error(f"         → Content is list/tuple with {len(content)} items")
                                                    content = ' '.join(str(c) for c in content)
                                                else:
                                                    logger.error(f"         → Converting to string directly")
                                                    content = str(content)
                                            except Exception as conv_err:
                                                logger.error(f"         ⚠️  Conversion error: {conv_err}")
                                                content = str(content)
                                        
                                        if not isinstance(content, str):
                                            logger.error(f"      ⚠️  Content is still not a string after conversion: {type(content)}")
                                            logger.error(f"         Content value: {str(content)[:200]}")
                                            content = None
                                        else:
                                            content_lower = content.lower()
                                            logger.error(f"      📄 Content preview (first 300 chars): {content[:300]}")
                                            logger.error(f"      📏 Content length: {len(content)}")
                                            
                                            # Check for error messages
                                            has_error = (
                                                "llm error" in content_lower or 
                                                "api error" in content_lower or 
                                                "invalid model" in content_lower or
                                                "not supported" in content_lower or
                                                "supported models" in content_lower
                                            )
                                            
                                            # Check if it's a substantial response (not just confirmation messages or errors)
                                            is_substantial = len(content) > 50 and (
                                                not has_error and
                                                "message added" not in content_lower and
                                                "successfully" not in content_lower and
                                                "message sent" not in content_lower
                                            )
                                            
                                            logger.error(f"      🔍 Analysis:")
                                            logger.error(f"         - has_error: {has_error}")
                                            logger.error(f"         - is_substantial: {is_substantial}")
                                            logger.error(f"         - is_assistant: {is_assistant}")
                                            
                                            if has_error:
                                                logger.error(f"      ⚠️  ERROR MESSAGE DETECTED - This is likely why API is not working!")
                                                logger.error(f"         Full error: {content[:500]}")
                                            
                                            if is_substantial:
                                                # CRITICAL: Only take ASSISTANT messages, never USER messages
                                                # The USER message is our prompt, not the AI response!
                                                if is_assistant:
                                                    response_text = content
                                                    logger.error("=" * 100)
                                                    logger.error(f"✅✅✅ SUCCESS! Found AI response in thread messages!")
                                                    logger.error(f"   Length: {len(response_text)}")
                                                    logger.error(f"   Role: {getattr(msg, 'role', msg.get('role', 'unknown') if isinstance(msg, dict) else 'unknown')}")
                                                    logger.error(f"   Preview: {response_text[:500]}")
                                                    logger.error("=" * 100)
                                                    break
                                                else:
                                                    logger.error(f"      ⏭️  Skipping non-assistant message (role: {getattr(msg, 'role', msg.get('role', 'unknown') if isinstance(msg, dict) else 'unknown')}) - This is the USER message (our prompt)")
                                            elif has_error:
                                                logger.error(f"      ⚠️  Skipping error message (not substantial)")
                                            else:
                                                logger.error(f"      ⏭️  Skipping (not substantial: length={len(content)}, is_assistant={is_assistant})")
                                                if content and len(content) > 10:
                                                    # Log shorter messages for debugging
                                                    logger.error(f"         Short message preview: {content[:100]}")
                                    else:
                                        logger.error(f"      ⚠️  No content found in message")
                                        # Try additional ways to get content
                                        if isinstance(msg, dict):
                                            # Try other possible keys
                                            for key in ['text', 'body', 'message', 'data', 'value']:
                                                if key in msg:
                                                    potential_content = msg[key]
                                                    if isinstance(potential_content, str) and len(potential_content) > 50:
                                                        logger.error(f"      Found content in '{key}': length={len(potential_content)}")
                                                        response_text = potential_content
                                                        break
                                        elif hasattr(msg, 'text'):
                                            potential_content = msg.text
                                            if isinstance(potential_content, str) and len(potential_content) > 50:
                                                logger.error(f"      Found content in .text attr: length={len(potential_content)}")
                                                response_text = potential_content
                                                break
                                    
                                    if response_text:
                                        break  # Exit loop if we found response
                            except Exception as msg_processing_error:
                                logger.error(f"❌ Exception in message processing loop: {msg_processing_error}", exc_info=True)
                                import traceback
                                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                        else:
                            logger.error(f"⚠️  Messages is falsy, skipping processing")
                    except Exception as fetch_error:
                        logger.error(f"❌ Exception fetching thread messages: {fetch_error}", exc_info=True)
                        import traceback
                        logger.error(f"❌ Traceback: {traceback.format_exc()}")
                        # Try multiple times with increasing waits
                        for retry_wait in [3, 5, 7]:
                            try:
                                await asyncio.sleep(retry_wait)
                                if hasattr(self._sdk_client, 'get_messages'):
                                    messages = await self._sdk_client.get_messages(thread_id=thread_id)
                                    if messages:
                                        msg_list = []
                                        if isinstance(messages, list):
                                            msg_list = messages
                                        elif hasattr(messages, 'messages'):
                                            msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                                        
                                        for msg in reversed(msg_list):
                                            content = None
                                            if hasattr(msg, 'content'):
                                                content = msg.content
                                            elif isinstance(msg, dict):
                                                content = msg.get('content', '')
                                            
                                            if content and len(content) > 50 and "llm error" not in content.lower():
                                                # Check if it's an assistant message
                                                is_assistant = False
                                                if hasattr(msg, 'role'):
                                                    role = msg.role
                                                    if hasattr(role, 'value'):
                                                        is_assistant = role.value in ['assistant', 'ai', 'bot']
                                                    else:
                                                        is_assistant = str(role).lower() in ['assistant', 'ai', 'bot']
                                                elif isinstance(msg, dict):
                                                    is_assistant = msg.get('role', '').lower() in ['assistant', 'ai', 'bot']
                                                
                                                if is_assistant or not hasattr(msg, 'role'):
                                                    response_text = content
                                                    logger.info(f"Found AI response on retry after {retry_wait}s wait (length: {len(response_text)})")
                                                    break
                                        
                                        if response_text:
                                            break
                            except Exception as retry_error:
                                logger.debug(f"Retry {retry_wait}s failed: {retry_error}")
                                continue
            
            # Extract response content from response object (if we haven't already)
            # This matches the logic in ticker_lookup.py
            if response_text is None or len(response_text.strip()) < 10:
                if response:
                    logger.error(f"🔍 Extracting from response object (type: {type(response)})...")
                    # Try multiple ways to extract content from response (same as ticker_lookup.py)
                    if hasattr(response, 'content'):
                        response_text = response.content
                        logger.error(f"✅ Found response.content: length: {len(response_text) if response_text else 0}")
                    elif hasattr(response, 'latest_message'):
                        if hasattr(response.latest_message, 'content'):
                            response_text = response.latest_message.content
                            logger.error(f"✅ Found response.latest_message.content: length: {len(response_text) if response_text else 0}")
                        elif isinstance(response.latest_message, dict):
                            response_text = response.latest_message.get('content', '')
                            logger.error(f"✅ Found response.latest_message dict: length: {len(response_text) if response_text else 0}")
                    elif hasattr(response, 'message'):
                        # Response has 'message' field instead of 'latest_message' (like ticker_lookup.py line 904-905)
                        msg_obj = response.message
                        if hasattr(msg_obj, 'content'):
                            response_text = msg_obj.content
                            logger.error(f"✅ Found response.message.content: length: {len(response_text) if response_text else 0}")
                        elif isinstance(msg_obj, dict):
                            response_text = msg_obj.get('content', '')
                            logger.error(f"✅ Found response.message dict: length: {len(response_text) if response_text else 0}")
                        else:
                            # Message might be the content itself
                            response_text = str(msg_obj)
                            logger.error(f"✅ Found response.message as string: length: {len(response_text) if response_text else 0}")
                    elif isinstance(response, dict):
                        # Try various keys (API might return 'message' instead of 'latest_message')
                        response_text = (
                            response.get('latest_message', {}).get('content', '') or
                            response.get('message', {}).get('content', '') or
                            response.get('content', '') or
                            response.get('text', '') or
                            str(response)
                        )
                        logger.error(f"✅ Found response dict: length: {len(response_text) if response_text else 0}")
                    else:
                        response_text = str(response)
                        logger.error(f"✅ Converted response to string: length: {len(response_text) if response_text else 0}")
                    
                    logger.info(f"Extracted response_text from response object (length: {len(response_text) if response_text else 0})")
                else:
                    response_text = ''
            
            # Log what we got for debugging
            logger.error("=" * 100)
            logger.error(f"📊 RESPONSE ANALYSIS:")
            logger.error(f"   response_text type: {type(response_text)}")
            logger.error(f"   response_text length: {len(response_text) if response_text else 0}")
            if response_text:
                logger.error(f"   response_text preview (first 1000 chars): {response_text[:1000]}")
            logger.error("=" * 100)
            
            if not response_text or len(response_text.strip()) < 10:
                logger.error(f"❌ Empty or very short response_text (length: {len(response_text) if response_text else 0}), using fallback")
                return self._parse_profile_fallback(onboarding_text)
            
            logger.error(f"✅ Got response_text with length: {len(response_text)}")
            
            logger.debug(f"Response text length: {len(response_text)}, first 200 chars: {response_text[:200]}")
            
            # Parse JSON response with multiple extraction strategies
            try:
                import re
                extracted_json = None
                
                # Strategy 1: Extract from markdown code blocks (```json ... ```)
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    extracted_json = json_match.group(1).strip()
                    logger.debug("Extracted JSON from markdown code block")
                
                # Strategy 2: Extract from markdown code blocks without language (``` ... ```)
                if not extracted_json:
                    json_match = re.search(r'```\s*(.*?)\s*```', response_text, re.DOTALL)
                    if json_match:
                        candidate = json_match.group(1).strip()
                        # Check if it looks like JSON (starts with {)
                        if candidate.startswith('{'):
                            extracted_json = candidate
                            logger.debug("Extracted JSON from generic code block")
                
                # Strategy 3: Find JSON object by matching braces (non-greedy, balanced)
                if not extracted_json:
                    # Find the first { and then match balanced braces
                    brace_count = 0
                    start_idx = response_text.find('{')
                    if start_idx != -1:
                        end_idx = start_idx
                        for i in range(start_idx, len(response_text)):
                            if response_text[i] == '{':
                                brace_count += 1
                            elif response_text[i] == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_idx = i + 1
                                    break
                        if brace_count == 0:
                            extracted_json = response_text[start_idx:end_idx]
                            logger.debug("Extracted JSON by matching braces")
                
                # Strategy 4: Try to find JSON object with regex (more permissive)
                if not extracted_json:
                    # Match JSON object that might span multiple lines
                    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                    if json_match:
                        extracted_json = json_match.group(0)
                        logger.debug("Extracted JSON with regex pattern")
                
                # Strategy 5: Try to clean and extract from the whole response
                if not extracted_json:
                    # Remove leading/trailing whitespace and try to parse
                    cleaned = response_text.strip()
                    # Remove any leading text before first {
                    first_brace = cleaned.find('{')
                    if first_brace != -1:
                        cleaned = cleaned[first_brace:]
                        # Try to find the last }
                        last_brace = cleaned.rfind('}')
                        if last_brace != -1:
                            cleaned = cleaned[:last_brace + 1]
                            extracted_json = cleaned
                            logger.debug("Extracted JSON by cleaning response")
                
                if not extracted_json or len(extracted_json.strip()) < 2:
                    logger.warning(f"No valid JSON found in response_text, trying fallback. Response: {response_text[:500]}")
                    return self._parse_profile_fallback(onboarding_text)
                
                # Try to parse the extracted JSON
                logger.error(f"🔍 Attempting to parse JSON (length: {len(extracted_json)})")
                logger.error(f"📋 JSON preview (first 500 chars): {extracted_json[:500]}")
                try:
                    profile_dict = json.loads(extracted_json)
                    logger.error(f"✅ Successfully parsed JSON - keys: {list(profile_dict.keys())}")
                    logger.error(f"   horizon_months: {profile_dict.get('horizon_months')}")
                    logger.error(f"   risk_score: {profile_dict.get('risk_score')}")
                except json.JSONDecodeError as json_error:
                    logger.error(f"❌ JSON parse error: {json_error}")
                    logger.warning(f"JSON decode error: {json_error}. Attempting to fix common issues...")
                    # Try to fix common JSON issues
                    # Remove trailing commas
                    fixed_json = re.sub(r',\s*}', '}', extracted_json)
                    fixed_json = re.sub(r',\s*]', ']', fixed_json)
                    # Remove comments (not valid in JSON but sometimes AI adds them)
                    fixed_json = re.sub(r'//.*?$', '', fixed_json, flags=re.MULTILINE)
                    fixed_json = re.sub(r'/\*.*?\*/', '', fixed_json, flags=re.DOTALL)
                    try:
                        profile_dict = json.loads(fixed_json)
                        logger.info("Successfully parsed JSON after fixing common issues")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON even after fixes. Extracted JSON: {extracted_json[:500]}")
                        return self._parse_profile_fallback(onboarding_text)
                
                # Validate and fix extracted values
                # CRITICAL: ALWAYS run text extraction and use it if it differs from AI default (60)
                # The AI often defaults to 60 even when explicit values are present
                logger.error("=" * 100)
                logger.error("🔧 POST-PROCESSING STARTED - This message should always appear!")
                logger.error(f"   profile_dict keys: {list(profile_dict.keys())}")
                logger.error(f"   profile_dict horizon: {profile_dict.get('horizon_months')}")
                logger.error(f"   profile_dict risk: {profile_dict.get('risk_score')}")
                logger.error(f"   Original text: '{onboarding_text[:200]}'")
                logger.error("=" * 100)
                try:
                    import re
                    logger.error("🔍 Calling _extract_horizon_from_text...")
                    text_horizon = self._extract_horizon_from_text(onboarding_text)
                    logger.error(f"✅ EXTRACTED text_horizon: {text_horizon}")
                    text_lower_check = onboarding_text.lower()
                    
                    # Check for explicit years/months in text
                    has_explicit_years = bool(re.search(r'\d+\s*years?', text_lower_check)) or bool(re.search(r'\d+\s*year\s+horizon', text_lower_check))
                    has_explicit_months = bool(re.search(r'\d+\s*months?', text_lower_check))
                    
                    # Log for debugging
                    logger.info(f"POST-PROCESS: text='{onboarding_text[:80]}', has_years={has_explicit_years}, has_months={has_explicit_months}, text_horizon={text_horizon}")
                    
                    if 'horizon_months' not in profile_dict or not isinstance(profile_dict.get('horizon_months'), int):
                        # Missing - use text extraction
                        profile_dict['horizon_months'] = text_horizon
                        logger.info(f"POST-PROCESS: Set missing horizon to {text_horizon}")
                    else:
                        ai_horizon = profile_dict['horizon_months']
                        logger.info(f"POST-PROCESS: AI={ai_horizon}, text={text_horizon}, explicit_years={has_explicit_years}, explicit_months={has_explicit_months}")
                        
                        # ALWAYS override if text extraction differs from AI and text extraction isn't default
                        # This catches cases where AI defaults to 60 but text has explicit values
                        should_override = False
                        if text_horizon != ai_horizon:
                            # Text extraction differs from AI
                            if has_explicit_years or has_explicit_months:
                                # Explicit value in text - always trust text extraction
                                should_override = True
                                logger.info(f"POST-PROCESS: OVERRIDE - explicit value in text, text={text_horizon} != AI={ai_horizon}")
                            elif ai_horizon == 60 and text_horizon != 60:
                                # AI defaulted to 60, but text extraction found something else
                                should_override = True
                                logger.info(f"POST-PROCESS: OVERRIDE - AI defaulted to 60, but text extraction found {text_horizon}")
                        
                        if should_override:
                            old_value = profile_dict['horizon_months']
                            profile_dict['horizon_months'] = text_horizon
                            logger.info(f"POST-PROCESS: OVERRIDDEN horizon from {old_value} to {text_horizon}")
                        elif ai_horizon < 0 or ai_horizon > 600:
                            # Out of range - fix it
                            horizon = max(0, min(600, ai_horizon))
                            profile_dict['horizon_months'] = horizon
                            logger.warning(f"POST-PROCESS: Adjusted out-of-range horizon to {horizon}")
                        else:
                            logger.debug(f"POST-PROCESS: Keeping AI value: {ai_horizon}")
                    
                    # Validate risk_score - ALWAYS check text extraction for explicit risk phrases
                    text_risk = self._extract_risk_from_text(onboarding_text)
                    text_lower = onboarding_text.lower()
                    has_explicit_risk = (
                        "risk averse" in text_lower or 
                        "i'm risk averse" in text_lower or 
                        "very conservative" in text_lower or
                        "conservative" in text_lower or 
                        "aggressive" in text_lower or 
                        "i'm aggressive" in text_lower or
                        "high risk" in text_lower or
                        "moderate risk" in text_lower or
                        "moderate" in text_lower or
                        "balanced" in text_lower
                    )
                    
                    logger.info(f"POST-PROCESS: risk - text_risk={text_risk}, has_explicit_risk={has_explicit_risk}")
                    
                    if 'risk_score' not in profile_dict or not isinstance(profile_dict.get('risk_score'), int):
                        # Missing - use text extraction
                        profile_dict['risk_score'] = text_risk
                        logger.info(f"POST-PROCESS: Set missing risk to {text_risk}")
                    else:
                        ai_risk = profile_dict['risk_score']
                        logger.info(f"POST-PROCESS: risk - AI={ai_risk}, text={text_risk}, has_explicit={has_explicit_risk}")
                        
                        # ALWAYS override if text extraction differs from AI and text extraction isn't default
                        # This catches cases where AI defaults to 50 but text has explicit risk phrases
                        should_override = False
                        if text_risk != ai_risk:
                            # Text extraction differs from AI
                            if has_explicit_risk:
                                # Explicit risk phrase in text - always trust text extraction
                                should_override = True
                                logger.info(f"POST-PROCESS: OVERRIDE - explicit risk phrase, text={text_risk} != AI={ai_risk}")
                            elif ai_risk == 50 and text_risk != 50:
                                # AI defaulted to 50, but text extraction found something else
                                should_override = True
                                logger.info(f"POST-PROCESS: OVERRIDE - AI defaulted to 50, but text extraction found {text_risk}")
                        
                        if should_override:
                            old_value = profile_dict['risk_score']
                            profile_dict['risk_score'] = text_risk
                            logger.info(f"POST-PROCESS: OVERRIDDEN risk from {old_value} to {text_risk}")
                        elif ai_risk < 0 or ai_risk > 100:
                            # Out of range - fix it
                            risk = max(0, min(100, ai_risk))
                            profile_dict['risk_score'] = risk
                            logger.warning(f"POST-PROCESS: Adjusted out-of-range risk to {risk}")
                        else:
                            logger.debug(f"POST-PROCESS: Keeping AI risk value: {ai_risk}")
                except Exception as post_process_error:
                    logger.error(f"Error in post-processing: {post_process_error}", exc_info=True)
                    # Continue anyway - don't fail the whole extraction
                
                # Validate objective
                if 'objective' not in profile_dict or not isinstance(profile_dict.get('objective'), dict):
                    obj_type = self._extract_objective_from_text(onboarding_text)
                    profile_dict['objective'] = {'type': obj_type, 'notes': onboarding_text[:100]}
                    logger.info(f"Extracted objective from text: {obj_type}")
                elif 'type' not in profile_dict.get('objective', {}):
                    obj_type = self._extract_objective_from_text(onboarding_text)
                    profile_dict['objective'] = {'type': obj_type, 'notes': profile_dict.get('objective', {}).get('notes', onboarding_text[:100])}
                    logger.info(f"Fixed objective type: {obj_type}")
                
                # Normalize sector names to exact sector names (also check the original text)
                if 'preferences' in profile_dict and 'sectors_like' in profile_dict['preferences']:
                    # Get sectors from both the extracted list and original text
                    sectors_from_list = get_sectors_by_keywords(' '.join(profile_dict['preferences']['sectors_like']))
                    sectors_from_text = get_sectors_by_keywords(onboarding_text)
                    all_sectors = sectors_from_list + sectors_from_text
                    normalized_sectors = list(set([s['name'] for s in all_sectors]))  # Remove duplicates
                    profile_dict['preferences']['sectors_like'] = normalized_sectors if normalized_sectors else profile_dict['preferences']['sectors_like']
                    
                if 'preferences' in profile_dict and 'sectors_avoid' in profile_dict['preferences']:
                    sectors = get_sectors_by_keywords(' '.join(profile_dict['preferences']['sectors_avoid']))
                    normalized_sectors = list(set([s['name'] for s in sectors]))
                    profile_dict['preferences']['sectors_avoid'] = normalized_sectors if normalized_sectors else profile_dict['preferences']['sectors_avoid']
                
                # Ensure preferences structure exists
                if 'preferences' not in profile_dict:
                    profile_dict['preferences'] = {}
                if 'sectors_like' not in profile_dict['preferences']:
                    profile_dict['preferences']['sectors_like'] = []
                if 'sectors_avoid' not in profile_dict['preferences']:
                    profile_dict['preferences']['sectors_avoid'] = []
                if 'regions_like' not in profile_dict['preferences']:
                    profile_dict['preferences']['regions_like'] = []
                
                # Extract constraints from text if not properly extracted
                if 'constraints' not in profile_dict:
                    profile_dict['constraints'] = {}
                
                # Extract max_holdings from text
                import re
                max_holdings_match = re.search(r'max(?:imum)?\s+(\d+)\s+holdings?', onboarding_text.lower())
                if max_holdings_match:
                    extracted_max = int(max_holdings_match.group(1))
                    if 'max_holdings' not in profile_dict.get('constraints', {}) or profile_dict['constraints'].get('max_holdings', 20) == 20:
                        # AI didn't extract it or used default - use text extraction
                        if 'max_holdings' not in profile_dict['constraints']:
                            profile_dict['constraints']['max_holdings'] = extracted_max
                        else:
                            profile_dict['constraints']['max_holdings'] = extracted_max
                        logger.info(f"Extracted max_holdings from text: {extracted_max}")
                
                # Extract max_position_pct from text - handle multiple patterns
                max_position_patterns = [
                    r'max(?:imum)?\s+(\d+(?:\.\d+)?)\s*%',  # "max 15%"
                    r'(\d+(?:\.\d+)?)\s*%\s+per\s+position',  # "15% per position"
                    r'no\s+.*?exceed\s+(\d+(?:\.\d+)?)\s*%',  # "no position exceed 15%"
                    r'should\s+not\s+exceed\s+(\d+(?:\.\d+)?)\s*%',  # "should not exceed 15%"
                ]
                max_position_match = None
                for pattern in max_position_patterns:
                    max_position_match = re.search(pattern, onboarding_text.lower())
                    if max_position_match:
                        break
                
                if max_position_match:
                    extracted_max_pct = float(max_position_match.group(1))
                    # Always override if we found explicit value in text
                    profile_dict['constraints']['max_position_pct'] = extracted_max_pct
                    logger.info(f"Extracted max_position_pct from text: {extracted_max_pct}")
                
                # Fix sector avoidance - check if text says "avoid" or "don't want"
                text_lower = onboarding_text.lower()
                avoid_patterns = [
                    r"avoid\s+([^,\.]+)",
                    r"don'?t\s+want\s+([^,\.]+)",
                    r"exclude\s+([^,\.]+)",
                    r"no\s+([^,\.]+)",
                ]
                avoided_sectors_from_text = []
                for pattern in avoid_patterns:
                    matches = re.findall(pattern, text_lower)
                    for match in matches:
                        # Extract sector names from the match
                        avoided_sectors = get_sectors_by_keywords(match)
                        avoided_sectors_from_text.extend([s['name'] for s in avoided_sectors])
                
                if avoided_sectors_from_text:
                    # Remove duplicates
                    avoided_sectors_from_text = list(set(avoided_sectors_from_text))
                    # Merge with AI extracted sectors_avoid
                    current_avoid = profile_dict.get('preferences', {}).get('sectors_avoid', [])
                    if isinstance(current_avoid, list):
                        all_avoided = list(set(current_avoid + avoided_sectors_from_text))
                    else:
                        all_avoided = avoided_sectors_from_text
                    profile_dict['preferences']['sectors_avoid'] = all_avoided
                    # Also remove from sectors_like if they're there
                    if 'sectors_like' in profile_dict.get('preferences', {}):
                        sectors_like = profile_dict['preferences']['sectors_like']
                        profile_dict['preferences']['sectors_like'] = [s for s in sectors_like if s not in all_avoided]
                    logger.info(f"Extracted sectors_avoid from text: {all_avoided}")
                
                # Ensure constraints structure exists
                if 'constraints' not in profile_dict:
                    profile_dict['constraints'] = {}
                
                # Final verification and FORCE override if needed
                # This is the LAST chance to fix values before creating the profile
                # ALWAYS run extraction and compare - if different, use extraction
                try:
                    text_horizon_final = self._extract_horizon_from_text(onboarding_text)
                    text_risk_final = self._extract_risk_from_text(onboarding_text)
                    text_lower_final = onboarding_text.lower()
                    
                    current_horizon = profile_dict.get('horizon_months', 60)
                    current_risk = profile_dict.get('risk_score', 50)
                    
                    logger.error("=" * 100)
                    logger.error(f"🎯 FINAL CHECK BEFORE PROFILE CREATION:")
                    logger.error(f"   current_horizon (from AI): {current_horizon}")
                    logger.error(f"   text_horizon (from extraction): {text_horizon_final}")
                    logger.error(f"   current_risk (from AI): {current_risk}")
                    logger.error(f"   text_risk (from extraction): {text_risk_final}")
                    logger.error(f"   horizon_match: {text_horizon_final == current_horizon}")
                    logger.error(f"   risk_match: {text_risk_final == current_risk}")
                    logger.error("=" * 100)
                    
                    # SIMPLE RULE: If text extraction differs from current value, use text extraction
                    # This catches all cases where AI defaulted incorrectly
                    if text_horizon_final != current_horizon:
                        logger.error(f"🔄 FINAL OVERRIDE HORIZON: {current_horizon} -> {text_horizon_final}")
                        profile_dict['horizon_months'] = text_horizon_final
                        logger.error(f"✅ Updated profile_dict['horizon_months'] = {profile_dict['horizon_months']}")
                    else:
                        logger.error(f"⏭️  Skipping horizon override (already correct: {current_horizon})")
                    
                    if text_risk_final != current_risk:
                        logger.error(f"🔄 FINAL OVERRIDE RISK: {current_risk} -> {text_risk_final}")
                        profile_dict['risk_score'] = text_risk_final
                        logger.error(f"✅ Updated profile_dict['risk_score'] = {profile_dict['risk_score']}")
                    else:
                        logger.error(f"⏭️  Skipping risk override (already correct: {current_risk})")
                except Exception as final_error:
                    logger.error(f"❌ Error in final override check: {final_error}", exc_info=True)
                
                # Final verification - log what we're about to create
                logger.error("=" * 100)
                logger.error(f"📦 FINAL PROFILE DICT VALUES BEFORE InvestorProfile() CREATION:")
                logger.error(f"   horizon_months: {profile_dict.get('horizon_months')}")
                logger.error(f"   risk_score: {profile_dict.get('risk_score')}")
                logger.error(f"   user_id: {profile_dict.get('user_id')}")
                logger.error(f"   objective: {profile_dict.get('objective')}")
                logger.error("=" * 100)
                
                try:
                    logger.error("🏗️  Creating InvestorProfile object...")
                    profile = InvestorProfile(**profile_dict)
                    logger.error("=" * 100)
                    logger.error(f"✅ SUCCESSFULLY CREATED PROFILE:")
                    logger.error(f"   profile.horizon_months: {profile.horizon_months}")
                    logger.error(f"   profile.risk_score: {profile.risk_score}")
                    logger.error(f"   profile.objective.type: {profile.objective.type}")
                    logger.error("=" * 100)
                    logger.info(f"Successfully extracted profile using Backboard AI - horizon: {profile.horizon_months}, risk: {profile.risk_score}, objective: {profile.objective.type}")
                    return profile
                except Exception as validation_error:
                    logger.warning(f"Profile validation error: {validation_error}. Attempting to fix...")
                    # Try to fix common validation issues
                    if 'user_id' not in profile_dict:
                        profile_dict['user_id'] = 'temp'  # Will be set by caller
                    if 'last_updated' not in profile_dict:
                        profile_dict['last_updated'] = datetime.utcnow().isoformat()
                    # CRITICAL: Ensure horizon_months and risk_score are set from text extraction if missing
                    if 'horizon_months' not in profile_dict or not isinstance(profile_dict.get('horizon_months'), int):
                        text_horizon = self._extract_horizon_from_text(onboarding_text)
                        profile_dict['horizon_months'] = text_horizon
                        logger.warning(f"Fixed missing horizon_months: set to {text_horizon}")
                    if 'risk_score' not in profile_dict or not isinstance(profile_dict.get('risk_score'), int):
                        text_risk = self._extract_risk_from_text(onboarding_text)
                        profile_dict['risk_score'] = text_risk
                        logger.warning(f"Fixed missing risk_score: set to {text_risk}")
                    try:
                        profile = InvestorProfile(**profile_dict)
                        logger.info("Successfully created profile after fixing validation issues")
                        return profile
                    except Exception as final_error:
                        logger.error(f"Failed to create profile even after fixes: {final_error}")
                        # Use fallback but ensure it extracts years correctly
                        return self._parse_profile_fallback(onboarding_text)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Failed to parse AI response as JSON: {e}. Using fallback.")
                return self._parse_profile_fallback(onboarding_text)
            
        except Exception as e:
            logger.error(f"Error in cheap_extract_profile: {e}", exc_info=True)
        
        # Fallback parsing
        return self._parse_profile_fallback(onboarding_text)
    
    async def cheap_update_profile(
        self, current_profile: InvestorProfile, update_text: str
    ) -> InvestorProfile:
        """Use CHEAP model to update InvestorProfile from update text."""
        if not self._sdk_client:
            # Fallback: apply simple keyword updates
            return self._update_profile_fallback(current_profile, update_text)
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                return self._update_profile_fallback(current_profile, update_text)
            
            # Load sector aliases for update prompt
            import json as json_module
            from pathlib import Path
            aliases_file = Path(__file__).parent.parent / "data" / "sector_aliases.json"
            with open(aliases_file, 'r') as f:
                aliases_data = json_module.load(f)
            
            # Build alias mapping for AI
            alias_mapping_text = ""
            for sector_name, sector_info in aliases_data['sector_aliases'].items():
                aliases = ", ".join(sector_info['aliases'][:8])
                alias_mapping_text += f"- {sector_info['exact_name']}: {aliases}\n"
            
            system_prompt = f"""Given existing InvestorProfile JSON and update_text, return updated InvestorProfile JSON only. Preserve fields not mentioned.

SECTOR ALIAS MAPPING (use EXACT sector names):
{alias_mapping_text}

For sectors_like and sectors_avoid, map any keywords to EXACT sector names (exact_name values only)."""
            
            prompt = f"""Current profile:
{json.dumps(current_profile.model_dump(), indent=2)}

Update request:
{update_text}

Return updated InvestorProfile JSON only."""
            
            # Use Backboard assistant to update profile via AI
            thread = await self._sdk_client.create_thread(assistant_id=assistant_id)
            
            # Get thread ID correctly
            thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
            
            full_prompt = f"{system_prompt}\n\n{prompt}"
            
            # Log input lengths for debugging
            logger.info(f"Profile update - update_text length: {len(update_text)}, full_prompt length: {len(full_prompt)}")
            
            response = None
            response_text = None
            
            try:
                response = await self._sdk_client.add_message(
                    thread_id=thread_id,
                    content=full_prompt,
                    llm_provider="openai",
                    model_name="gpt-4o-mini"  # Cheap model
                )
                logger.info(f"Successfully sent update message to Backboard SDK (content length: {len(full_prompt)})")
            except Exception as e:
                # If add_message fails with validation error, fetch from thread messages
                error_msg = str(e)
                logger.warning(f"Backboard add_message failed (content length: {len(full_prompt)}), error: {error_msg}")
                # Check if error mentions content length or truncation
                if "length" in error_msg.lower() or "too long" in error_msg.lower() or "truncat" in error_msg.lower() or "max" in error_msg.lower():
                    logger.error(f"Content length issue detected in update! Full error: {e}")
                    # Try to send with a shorter system prompt
                    short_system = "Update the investor profile based on the update request. Return ONLY updated InvestorProfile JSON."
                    short_prompt = f"{short_system}\n\nCurrent profile:\n{json.dumps(current_profile.model_dump(), indent=2)}\n\nUpdate request:\n{update_text}\n\nReturn updated InvestorProfile JSON only."
                    logger.info(f"Retrying update with shorter prompt (length: {len(short_prompt)})")
                    try:
                        response = await self._sdk_client.add_message(
                            thread_id=thread_id,
                            content=short_prompt,
                            llm_provider="openai",
                            model_name="gpt-4o-mini"
                        )
                        logger.info("Successfully sent shortened update message")
                    except Exception as retry_error:
                        logger.error(f"Retry with shortened prompt also failed: {retry_error}")
                import asyncio
                await asyncio.sleep(4)
                
                try:
                    messages = None
                    if hasattr(self._sdk_client, 'get_messages'):
                        messages = await self._sdk_client.get_messages(thread_id=thread_id)
                    elif hasattr(self._sdk_client, 'list_messages'):
                        messages = await self._sdk_client.list_messages(thread_id=thread_id)
                    elif hasattr(self._sdk_client, 'get_thread'):
                        thread_obj = await self._sdk_client.get_thread(thread_id=thread_id)
                        if hasattr(thread_obj, 'messages'):
                            messages = thread_obj.messages
                    
                    if messages:
                        msg_list = []
                        if isinstance(messages, list):
                            msg_list = messages
                        elif hasattr(messages, 'messages'):
                            msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                        
                        for msg in reversed(msg_list):
                            is_assistant = False
                            if hasattr(msg, 'role'):
                                role = msg.role
                                if hasattr(role, 'value'):
                                    is_assistant = role.value in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role)
                                else:
                                    is_assistant = str(role).lower() in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role).upper()
                            elif isinstance(msg, dict):
                                is_assistant = msg.get('role', '').lower() in ['assistant', 'ai', 'bot']
                            
                            content = None
                            if hasattr(msg, 'content'):
                                content = msg.content
                            elif isinstance(msg, dict):
                                content = msg.get('content', '')
                            
                            if content:
                                content_lower = content.lower()
                                # Check if it's a substantial response (not just confirmation messages)
                                is_substantial = len(content) > 50 and (
                                    "llm error" not in content_lower and 
                                    "api error" not in content_lower and 
                                    "invalid model" not in content_lower and
                                    "message added" not in content_lower and
                                    "successfully" not in content_lower
                                )
                                if is_substantial:
                                    if is_assistant or not hasattr(msg, 'role'):
                                        response_text = content
                                        logger.info(f"Found AI response in thread messages (length: {len(response_text)}, role: {getattr(msg, 'role', 'unknown')})")
                                        break
                                elif content and len(content) > 10:
                                    # Log shorter messages for debugging
                                    logger.debug(f"Skipping message (length: {len(content)}, role: {getattr(msg, 'role', 'unknown')}): {content[:100]}")
                except Exception as fetch_error:
                    logger.warning(f"Could not fetch thread messages: {fetch_error}")
                    # Try one more time after a longer wait
                    try:
                        await asyncio.sleep(3)
                        if hasattr(self._sdk_client, 'get_messages'):
                            messages = await self._sdk_client.get_messages(thread_id=thread_id)
                            if messages and isinstance(messages, list):
                                for msg in reversed(messages):
                                    if hasattr(msg, 'content'):
                                        content = msg.content
                                        if content and len(content) > 50 and "llm error" not in content.lower():
                                            response_text = content
                                            logger.info(f"Found AI response on retry (length: {len(response_text)})")
                                            break
                    except Exception:
                        pass
            
            # Extract and parse response
            if response_text is None:
                if response:
                    if hasattr(response, 'content'):
                        response_text = response.content
                    elif isinstance(response, dict):
                        response_text = response.get('content', '{}')
                    else:
                        response_text = str(response)
                else:
                    response_text = ''
            
            # Validate response_text before parsing
            if not response_text or len(response_text.strip()) < 10:
                logger.warning(f"Empty or very short response_text (length: {len(response_text) if response_text else 0}), using fallback")
                return self._update_profile_fallback(current_profile, update_text)
            
            logger.debug(f"Response text length: {len(response_text)}, first 200 chars: {response_text[:200]}")
            
            try:
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)
                else:
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        response_text = json_match.group(0)
                    else:
                        logger.warning(f"No JSON found in response_text, trying fallback. Response: {response_text[:500]}")
                        return self._update_profile_fallback(current_profile, update_text)
                
                if not response_text or len(response_text.strip()) < 2:
                    logger.warning("Extracted JSON is empty, using fallback")
                    return self._update_profile_fallback(current_profile, update_text)
                
                profile_dict = json.loads(response_text)
                # Normalize sector names
                from .sector_data import get_sectors_by_keywords
                if 'preferences' in profile_dict and 'sectors_like' in profile_dict['preferences']:
                    sectors_from_list = get_sectors_by_keywords(' '.join(profile_dict['preferences']['sectors_like']))
                    sectors_from_text = get_sectors_by_keywords(update_text)
                    all_sectors = sectors_from_list + sectors_from_text
                    normalized_sectors = list(set([s['name'] for s in all_sectors]))
                    profile_dict['preferences']['sectors_like'] = normalized_sectors if normalized_sectors else profile_dict['preferences']['sectors_like']
                    
                if 'preferences' in profile_dict and 'sectors_avoid' in profile_dict['preferences']:
                    sectors = get_sectors_by_keywords(' '.join(profile_dict['preferences']['sectors_avoid']))
                    normalized_sectors = list(set([s['name'] for s in sectors]))
                    profile_dict['preferences']['sectors_avoid'] = normalized_sectors if normalized_sectors else profile_dict['preferences']['sectors_avoid']
                
                updated_profile = InvestorProfile(**profile_dict)
                logger.info("Successfully updated profile using Backboard AI")
                return updated_profile
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Failed to parse AI response: {e}. Using fallback.")
                return self._update_profile_fallback(current_profile, update_text)
        except Exception as e:
            logger.error(f"Error in cheap_update_profile: {e}", exc_info=True)
            return self._update_profile_fallback(current_profile, update_text)
    
    async def strong_generate_explanation(
        self,
        profile: InvestorProfile,
        metrics_json: dict,
        plan_json: dict,
    ) -> str:
        """Use STRONG model to generate explanation narrative."""
        if self.budget_mode:
            return self._generate_template_explanation(profile, metrics_json, plan_json)
        
        if not self._sdk_client:
            return self._generate_template_explanation(profile, metrics_json, plan_json)
        
        try:
            assistant_id = await self._ensure_assistant()
            if not assistant_id:
                return self._generate_template_explanation(profile, metrics_json, plan_json)
            
            is_new_portfolio = plan_json.get('_is_new_portfolio', False)
            plan_type = "new portfolio construction" if is_new_portfolio else "rebalance"
            
            # Check if portfolio is risk-averse
            is_risk_averse = profile.risk_score < 50
            risk_note = ""
            if is_risk_averse:
                risk_note = f"\n\nIMPORTANT: This client is RISK-AVERSE (risk score: {profile.risk_score}/100). Emphasize:\n- Enhanced diversification across sectors (max 20-25% per sector)\n- Higher defensive allocations (bonds, low-volatility stocks)\n- Higher cash reserves for safety\n- Reduced concentration risk\n- Why diversification is critical for risk-averse portfolios"
            
            system_prompt = f"""You are a sophisticated investment advisor. Provide a clear, personalized explanation of the {plan_type} plan that ties each recommendation directly to the user's profile and current portfolio state. Be specific about why each action is recommended.{risk_note}

Structure your response as:
1. **Overview** (2-3 sentences): Summary of what's changing and why, referencing key profile attributes (risk score, horizon, objective). If risk-averse, emphasize risk management and diversification.
2. **Key Recommendations** (3-5 bullets): For each major action (BUY/SELL), explain:
   - What ticker/sector is being adjusted
   - Why this aligns with their profile (e.g., "Adding X sector exposure aligns with your {profile.risk_score}/100 risk tolerance and {profile.horizon_months}-month horizon")
   - How it moves toward target allocation
   - For risk-averse clients: Explain how this maintains sector diversification (no single sector >20-25%)
3. **Portfolio Improvements** (2-3 bullets): Explain improvements in:
   - Sector diversification (if concentration improved, mention sector weight limits enforced)
   - Risk management (if moving toward target risk profile, emphasize for risk-averse)
   - Sector alignment (if better matching preferred sectors, but balanced with diversification needs)
   - Defensive positioning (for risk-averse clients)
4. **Considerations** (1-2 bullets): Assumptions, risks, or tradeoffs

Be concise but specific. Reference actual tickers, sectors, and profile numbers. For risk-averse clients, always emphasize how the portfolio maintains proper sector diversification (max 20-25% per sector) even when incorporating preferred sectors. No generic financial advice language."""
            
            # Extract enhanced context if available
            current_context = metrics_json.get('current_portfolio_context', {})
            target_context = metrics_json.get('target_context', {})
            profile_factors = target_context.get('profile_key_factors', {})
            
            # Build detailed context string
            context_parts = []
            
            if current_context:
                if is_new_portfolio:
                    context_parts.append(f"### CONSTRUCTED PORTFOLIO:")
                    if 'constructed_portfolio' in current_context:
                        holdings_str = "\n".join([
                            f"  - {h['ticker']}: {h['weight_pct']}% ({h['sector']})"
                            for h in current_context['constructed_portfolio'][:15]  # Show all constructed
                        ])
                        context_parts.append(f"Portfolio Holdings:\n{holdings_str}")
                    if 'total_holdings_constructed' in current_context:
                        context_parts.append(f"Total Holdings: {current_context['total_holdings_constructed']}")
                else:
                    context_parts.append(f"### CURRENT PORTFOLIO STATE:")
                    if 'current_holdings' in current_context:
                        holdings_str = "\n".join([
                            f"  - {h['ticker']}: {h['weight_pct']}% ({h['sector']})"
                            for h in current_context['current_holdings'][:10]  # Top 10
                        ])
                        context_parts.append(f"Top Holdings:\n{holdings_str}")
                    if 'current_cash_pct' in current_context:
                        context_parts.append(f"Current Cash: {current_context['current_cash_pct']}%")
                
                # Sector allocation (works for both new and rebalance)
                sector_key = 'sector_allocation' if is_new_portfolio else 'current_sector_allocation'
                if sector_key in current_context or 'sector_allocation' in current_context:
                    sector_data = current_context.get(sector_key) or current_context.get('sector_allocation', {})
                    if sector_data:
                        sectors_str = ", ".join([
                            f"{sector}: {pct}%"
                            for sector, pct in sorted(sector_data.items(), 
                                                     key=lambda x: x[1], reverse=True)[:5]
                        ])
                        label = "Portfolio Sector Allocation" if is_new_portfolio else "Current Sector Allocation"
                        context_parts.append(f"{label}: {sectors_str}")
                
                if 'concentration_analysis' in current_context:
                    conc = current_context['concentration_analysis']
                    context_parts.append(
                        f"Concentration: Top 1 holding = {conc.get('top_1_pct', 0)}%, "
                        f"Top 3 = {conc.get('top_3_pct', 0)}%, HHI = {conc.get('hhi', 0)}"
                    )
                context_parts.append("")
            
            if target_context:
                context_parts.append(f"### TARGET ALLOCATION:")
                target_alloc = target_context.get('target_allocation', {})
                context_parts.append(
                    f"  Cash: {target_alloc.get('cash_pct', 0)}%, "
                    f"Core Equity: {target_alloc.get('core_equity_pct', 0)}%, "
                    f"Thematic: {target_alloc.get('thematic_sectors_pct', 0)}%, "
                    f"Defensive: {target_alloc.get('defensive_pct', 0)}%"
                )
                context_parts.append("")
                
                context_parts.append(f"### PROFILE FACTORS DRIVING RECOMMENDATIONS:")
                if profile_factors:
                    context_parts.append(f"  Risk Score: {profile_factors.get('risk_score', 'N/A')}/100")
                    context_parts.append(f"  Investment Horizon: {profile_factors.get('horizon_months', 'N/A')} months")
                    context_parts.append(f"  Objective: {profile_factors.get('objective', 'N/A').upper()}")
                    if profile_factors.get('preferred_sectors'):
                        context_parts.append(f"  Preferred Sectors: {', '.join(profile_factors['preferred_sectors'])}")
                    if profile_factors.get('excluded_sectors'):
                        context_parts.append(f"  Excluded Sectors: {', '.join(profile_factors['excluded_sectors'])}")
                    context_parts.append(f"  Max Holdings: {profile_factors.get('max_holdings', 'N/A')}")
                    context_parts.append(f"  Max Position Size: {profile_factors.get('max_position_pct', 'N/A')}%")
                context_parts.append("")
            
            context_str = "\n".join(context_parts) if context_parts else ""
            
            prompt = f"""{context_str}
### RECOMMENDED ACTIONS ({plan_type}):
{json.dumps(plan_json.get('actions', []), indent=2)}

### PLAN NOTES:
{chr(10).join(plan_json.get('notes', []))}

### WARNINGS:
{chr(10).join(plan_json.get('warnings', []))}

Generate a personalized explanation that:
1. References specific profile attributes (risk score {profile.risk_score}/100, {profile.horizon_months}-month horizon, {profile.objective.type} objective)
2. Explains how each major action (BUY/SELL) aligns with their goals
3. Highlights portfolio improvements (diversification, sector alignment, risk management)
4. Uses specific numbers from the current portfolio and target allocation

Be specific and actionable. Reference actual tickers and sectors mentioned in the plan."""
            
            # Use Backboard assistant with STRONG model for explanation
            thread = await self._sdk_client.create_thread(assistant_id=assistant_id)
            
            # Get thread ID correctly
            thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
            
            full_prompt = f"{system_prompt}\n\n{prompt}"
            
            response = None
            explanation = None
            
            try:
                response = await self._sdk_client.add_message(
                    thread_id=thread_id,
                    content=full_prompt,
                    llm_provider="openai",
                    model_name="gpt-4o"  # Strong model for explanations
                )
            except Exception as e:
                # If add_message fails with validation error, fetch from thread messages
                logger.warning(f"Backboard add_message failed, trying to get thread messages: {e}")
                import asyncio
                await asyncio.sleep(4)
                
                try:
                    messages = None
                    if hasattr(self._sdk_client, 'get_messages'):
                        messages = await self._sdk_client.get_messages(thread_id=thread_id)
                    elif hasattr(self._sdk_client, 'list_messages'):
                        messages = await self._sdk_client.list_messages(thread_id=thread_id)
                    elif hasattr(self._sdk_client, 'get_thread'):
                        thread_obj = await self._sdk_client.get_thread(thread_id=thread_id)
                        if hasattr(thread_obj, 'messages'):
                            messages = thread_obj.messages
                    
                    if messages:
                        msg_list = []
                        if isinstance(messages, list):
                            msg_list = messages
                        elif hasattr(messages, 'messages'):
                            msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                        
                        for msg in reversed(msg_list):
                            is_assistant = False
                            if hasattr(msg, 'role'):
                                role = msg.role
                                if hasattr(role, 'value'):
                                    is_assistant = role.value in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role)
                                else:
                                    is_assistant = str(role).lower() in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role).upper()
                            elif isinstance(msg, dict):
                                is_assistant = msg.get('role', '').lower() in ['assistant', 'ai', 'bot']
                            
                            content = None
                            if hasattr(msg, 'content'):
                                content = msg.content
                            elif isinstance(msg, dict):
                                content = msg.get('content', '')
                            
                            if content:
                                content_lower = content.lower()
                                # Check if it's a substantial response (not just confirmation messages)
                                is_substantial = len(content) > 50 and (
                                    "llm error" not in content_lower and 
                                    "api error" not in content_lower and 
                                    "invalid model" not in content_lower and
                                    "message added" not in content_lower and
                                    "successfully" not in content_lower
                                )
                                if is_substantial:
                                    if is_assistant or not hasattr(msg, 'role'):
                                        explanation = content
                                        logger.info(f"Found AI response in thread messages (length: {len(explanation)}, role: {getattr(msg, 'role', 'unknown')})")
                                        break
                                elif content and len(content) > 10:
                                    # Log shorter messages for debugging
                                    logger.debug(f"Skipping message (length: {len(content)}, role: {getattr(msg, 'role', 'unknown')}): {content[:100]}")
                except Exception as fetch_error:
                    logger.warning(f"Could not fetch thread messages: {fetch_error}")
            
            # Extract response content
            if explanation is None:
                if response:
                    if hasattr(response, 'content'):
                        explanation = response.content
                    elif isinstance(response, dict):
                        explanation = response.get('content', '')
                    else:
                        explanation = str(response)
                else:
                    explanation = ''
            
            if explanation and len(explanation) > 50:  # Valid response
                logger.info("Successfully generated explanation using Backboard AI")
                return explanation
            else:
                logger.warning("AI response too short, using template")
                return self._generate_template_explanation(profile, metrics_json, plan_json)
        except Exception as e:
            logger.error(f"Error generating AI explanation: {e}", exc_info=True)
            return self._generate_template_explanation(profile, metrics_json, plan_json)
    
    def _extract_horizon_from_text(self, text: str) -> int:
        """Extract investment horizon in months from text."""
        import re
        text_lower = text.lower()
        
        logger.error(f"_extract_horizon_from_text called with: '{text[:100]}'")
        
        # PRIORITY 1: Check for explicit years (most specific)
        # Look for patterns like "3 years", "10 years", "retirement in 10 years"
        years_patterns = [
            r'retirement\s+in\s+(\d+)\s*years?',  # "retirement in 10 years"
            r'investing\s+for\s+(\d+)\s*years?',   # "investing for 20 years"
            r'investment\s+(?:horizon|timeline)\s+is\s+(\d+)\s*years?',  # "investment horizon/timeline is 5 years"
            r'(\d+)\s*year\s+horizon',  # "7 year horizon"
            r'(\d+)\s*years?',  # "3 years", "5 years", etc. (catch-all, must be last)
        ]
        for pattern in years_patterns:
            years_match = re.search(pattern, text_lower)
            if years_match:
                years = int(years_match.group(1))
                result = years * 12
                logger.error(f"_extract_horizon_from_text: Pattern '{pattern}' matched '{years_match.group(1)}' -> {result} months")
                return result
        
        # PRIORITY 2: Check for explicit months
        months_patterns = [
            r'need\s+(?:cash|money)\s+in\s+(\d+)\s*months?',  # "need cash in 24 months"
            r'(\d+)\s*months?',  # "18 months", "24 months", etc.
        ]
        for pattern in months_patterns:
            months_match = re.search(pattern, text_lower)
            if months_match:
                return int(months_match.group(1))
        
        # PRIORITY 3: Check for horizon keywords
        if "long horizon" in text_lower or "long term" in text_lower or "long-term" in text_lower:
            return 60
        if "short horizon" in text_lower or "short term" in text_lower or "short-term" in text_lower:
            return 12
        if "early investor" in text_lower or "early stage" in text_lower:
            return 72
        if "retirement" in text_lower or "retire" in text_lower:
            # Check if there's a year mentioned with retirement
            retirement_years = re.search(r'retirement.*?(\d+)\s*years?', text_lower)
            if retirement_years:
                return int(retirement_years.group(1)) * 12
            return 180
        
        # Default
        return 60
    
    def _extract_risk_from_text(self, text: str) -> int:
        """Extract risk score (0-100) from text."""
        text_lower = text.lower()
        
        # Check for explicit risk averse phrases first (most specific)
        if "risk averse" in text_lower or "i'm risk averse" in text_lower:
            return 25
        if "very conservative" in text_lower or "very low risk" in text_lower:
            return 20
        if "conservative" in text_lower or "low risk" in text_lower:
            return 25
        
        # Moderate/balanced
        if "moderate risk" in text_lower or "moderate" in text_lower:
            return 50
        if "balanced" in text_lower or "balanced approach" in text_lower:
            return 50
        
        # Aggressive
        if "very aggressive" in text_lower or "very high risk" in text_lower:
            return 85
        if "aggressive" in text_lower or "i'm aggressive" in text_lower or "high risk" in text_lower or "risk tolerant" in text_lower:
            return 75
        
        # Default
        return 50
    
    def _extract_objective_from_text(self, text: str) -> str:
        """Extract investment objective type from text."""
        text_lower = text.lower()
        
        if "growth" in text_lower or "capital appreciation" in text_lower:
            return "growth"
        if "income" in text_lower or "dividend" in text_lower or "yield" in text_lower:
            return "income"
        
        # Default
        return "balanced"
    
    def _parse_profile_fallback(self, text: str) -> InvestorProfile:
        """Fallback parser for demo when API key not set."""
        logger.error("=" * 100)
        logger.error(f"🔄 FALLBACK PARSER CALLED - text: '{text[:200]}'")
        logger.error("=" * 100)
        
        text_lower = text.lower()
        
        # Extract objective
        if "income" in text_lower:
            obj_type = "income"
        elif "growth" in text_lower:
            obj_type = "growth"
        else:
            obj_type = "balanced"
        
        # Extract risk - FIXED to handle "risk averse" and other phrases
        if "risk averse" in text_lower or "i'm risk averse" in text_lower:
            risk_score = 25
            logger.error(f"✅ FALLBACK: Extracted risk averse -> {risk_score}")
        elif "very conservative" in text_lower or "very low risk" in text_lower:
            risk_score = 20
            logger.error(f"✅ FALLBACK: Extracted very conservative -> {risk_score}")
        elif "conservative" in text_lower or "low risk" in text_lower or "low" in text_lower:
            risk_score = 30
            logger.error(f"✅ FALLBACK: Extracted conservative -> {risk_score}")
        elif "aggressive" in text_lower or "i'm aggressive" in text_lower or "high risk" in text_lower or "high" in text_lower:
            risk_score = 70
            logger.error(f"✅ FALLBACK: Extracted aggressive -> {risk_score}")
        elif "moderate risk" in text_lower or "moderate" in text_lower:
            risk_score = 50
            logger.error(f"✅ FALLBACK: Extracted moderate -> {risk_score}")
        elif "balanced" in text_lower:
            risk_score = 50
            logger.error(f"✅ FALLBACK: Extracted balanced -> {risk_score}")
        else:
            risk_score = 50
            logger.error(f"⏭️  FALLBACK: Using default risk -> {risk_score}")
        
        # Extract horizon - FIXED to handle years too - USE THE METHOD!
        # Use the extraction method instead of inline code
        horizon = self._extract_horizon_from_text(text)
        logger.error(f"✅ FALLBACK: Extracted horizon -> {horizon} months")
        
        # Extract max holdings
        max_holdings = 20
        max_match = re.search(r'max\s*(\d+)\s*holdings?', text_lower)
        if max_match:
            max_holdings = int(max_match.group(1))
        
        # Extract max position
        max_position = 25.0
        pos_match = re.search(r'max\s*(\d+)\s*%', text_lower)
        if pos_match:
            max_position = float(pos_match.group(1))
        
        # Extract exclusions
        exclusions = []
        if "avoid" in text_lower or "exclude" in text_lower:
            avoid_match = re.search(r'(?:avoid|exclude)\s+([^.]+)', text_lower)
            if avoid_match:
                exclusions = [w.strip() for w in avoid_match.group(1).split(",")]
        
        # Extract sector preferences using sector data
        from .sector_data import get_sectors_by_keywords
        sectors = get_sectors_by_keywords(text)
        sectors_like = [s['name'] for s in sectors]
        sectors_avoid = []
        
        # Extract sectors to avoid from text
        if exclusions:
            avoid_sectors = get_sectors_by_keywords(' '.join(exclusions))
            sectors_avoid = [s['name'] for s in avoid_sectors]
        
        # Rebalance frequency
        freq = "quarterly"
        if "monthly" in text_lower:
            freq = "monthly"
        elif "annual" in text_lower or "yearly" in text_lower:
            freq = "annual"
        
        from .models import Objective, Constraints, Preferences
        
        return InvestorProfile(
            user_id="temp",  # Will be set by caller
            objective=Objective(type=obj_type, notes=text[:100]),
            horizon_months=horizon,
            risk_score=risk_score,
            constraints=Constraints(
                max_holdings=max_holdings,
                max_position_pct=max_position,
                exclusions=exclusions,
            ),
            preferences=Preferences(sectors_like=sectors_like, sectors_avoid=sectors_avoid),
            rebalance_frequency=freq,
        )
    
    def _update_profile_fallback(
        self, profile: InvestorProfile, update_text: str
    ) -> InvestorProfile:
        """Fallback updater for demo."""
        text_lower = update_text.lower()
        updated = profile.model_copy(deep=True)
        
        # Update risk
        if "lower risk" in text_lower or "reduce risk" in text_lower:
            updated.risk_score = max(0, profile.risk_score - 20)
        elif "higher risk" in text_lower or "increase risk" in text_lower:
            updated.risk_score = min(100, profile.risk_score + 20)
        
        # Update horizon (cash need)
        if "cash" in text_lower and "month" in text_lower:
            months = re.findall(r'(\d+)\s*month', text_lower)
            if months:
                updated.horizon_months = min(profile.horizon_months, int(months[0]))
        
        
        updated.last_updated = datetime.utcnow().isoformat()
        return updated
    
    def _generate_template_explanation(
        self, profile: InvestorProfile, metrics_json: dict, plan_json: dict
    ) -> str:
        """Generate template-based explanation (budget mode)."""
        plan = plan_json
        is_new_portfolio = plan_json.get('_is_new_portfolio', False)
        plan_type = "New Portfolio Construction" if is_new_portfolio else "Rebalance Recommendation"
        actions_count = len(plan.get("actions", []))
        
        explanation = f"""{plan_type} for {profile.objective.type} objective:

• Target allocation reflects your {profile.horizon_months}-month horizon and {profile.risk_score}/100 risk score
"""
        
        if is_new_portfolio:
            explanation += f"• Constructed portfolio with {actions_count} holdings based on your preferences\n"
        else:
            explanation += f"• {actions_count} adjustments recommended to align with constraints\n"
        
        if profile.preferences.sectors_like:
            explanation += f"• Thematic focus maintained on: {', '.join(profile.preferences.sectors_like)}\n"
        
        if plan.get("warnings"):
            explanation += f"• Warnings: {'; '.join(plan['warnings'][:2])}\n"
        
        if is_new_portfolio:
            explanation += f"""
Assumptions: Portfolio constructed based on your investment profile. Rebalancing recommended every {profile.rebalance_frequency} per your preference.
Risks / tradeoffs: Diversification does not guarantee returns. Market movements may require ongoing adjustments. No guarantees on returns.
"""
        else:
            explanation += f"""
Assumptions: Rebalancing to target every {profile.rebalance_frequency} per your preference.
Risks / tradeoffs: Market movements may require ongoing adjustments. No guarantees on returns.
"""
        
        return explanation
