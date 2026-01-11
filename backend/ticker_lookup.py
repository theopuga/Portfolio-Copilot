"""Ticker lookup and classification with web search."""

import json
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from .sector_data import load_sectors_data, SECTORS_FILE

logger = logging.getLogger(__name__)


def ticker_exists(ticker: str) -> bool:
    """Check if ticker exists in database."""
    data = load_sectors_data()
    ticker_upper = ticker.upper()
    
    for sector in data['sectors']:
        for stock in sector['stocks']:
            if stock['ticker'].upper() == ticker_upper:
                return True
    return False


async def search_and_classify_ticker(ticker: str) -> Optional[Dict]:
    """
    Search web for ticker information and classify it using AI.
    
    Returns:
        Dict with: ticker, name, sector, market_cap, industry_risk
        Or None if no match found
    """
    ticker_upper = ticker.upper()
    
    try:
        # Try Backboard API first (if available)
        classification = await _classify_ticker_with_backboard(ticker_upper)
        
        if classification:
            logger.info(f"Successfully classified ticker {ticker_upper} using Backboard: {classification}")
            return classification
        
        # Fallback to OpenAI API (if available)
        logger.info(f"Backboard not available, trying OpenAI for {ticker_upper}")
        classification = await _classify_ticker_with_openai(ticker_upper)
        
        if classification:
            logger.info(f"Successfully classified ticker {ticker_upper} using OpenAI: {classification}")
            return classification
        
        # Fallback to web search + parsing approach
        logger.info(f"OpenAI not available, trying web search approach for {ticker_upper}")
        classification = await _classify_ticker_with_web_search(ticker_upper)
        
        if classification:
            logger.info(f"Successfully classified ticker {ticker_upper} using web search: {classification}")
            return classification
        else:
            logger.warning(f"Could not classify ticker {ticker_upper} from web search")
            return None
                
    except Exception as e:
        logger.error(f"Error searching for ticker {ticker_upper}: {e}", exc_info=True)
        return None


async def _classify_ticker_with_backboard(ticker: str) -> Optional[Dict]:
    """
    Use Backboard API to search and classify ticker.
    
    Returns classification dict or None if Backboard is not available.
    """
    import os
    
    # Check if Backboard API key is available
    backboard_api_key = os.getenv("BACKBOARD_API_KEY")
    if not backboard_api_key:
        logger.debug("BACKBOARD_API_KEY not set, skipping Backboard classification")
        return None
    
    try:
        from .backboard_client import BackboardClient
        backboard_client = BackboardClient()
        
        if not backboard_client._sdk_client:
            logger.debug("Backboard SDK client not initialized, skipping Backboard classification")
            return None
        
        # Get list of valid sectors for validation
        sectors_data = load_sectors_data()
        valid_sectors = [s['name'] for s in sectors_data['sectors']]
        sectors_list = ", ".join(valid_sectors)
        
        system_prompt = f"""You are a financial data classifier. Search the web for current information about stock tickers.

Return ONLY valid JSON with this exact structure:
{{
  "ticker": "{ticker}",
  "name": "Company Name",
  "sector": "One of: {sectors_list}",
  "market_cap": "large|medium|small|etf",
  "industry_risk": "low|medium|high|very_high"
}}

Valid sectors: {sectors_list}
Market cap: large (>$10B), medium ($2-10B), small (<$2B), etf (ETF/fund)
Industry risk: low, medium, high, very_high

If you cannot find the ticker, return: {{"error": "Ticker not found"}}"""
        
        user_prompt = f"""Search for current information about stock ticker: {ticker}

Extract and return ONLY JSON with:
1. Company name (full official name)
2. Sector (EXACTLY one of: {sectors_list})
3. Market cap: "large" (>$10B), "medium" ($2-10B), "small" (<$2B), or "etf"
4. Industry risk: "low", "medium", "high", or "very_high"

Example for AAPL:
{{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "market_cap": "large",
  "industry_risk": "medium"
}}

Return JSON only, no explanation."""
        
        # Get assistant
        assistant_id = await backboard_client._ensure_assistant()
        if not assistant_id:
            logger.debug("Could not get Backboard assistant, skipping Backboard classification")
            return None
        
        # Create thread
        thread = await backboard_client._sdk_client.create_thread(assistant_id=assistant_id)
        thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
        
        # Send message - try without model first (use assistant default)
        response = None
        response_text = None
        
        try:
            # Try calling without model_name (use assistant's default model)
            try:
                response = await backboard_client._sdk_client.add_message(
                    thread_id=thread_id,
                    content=f"{system_prompt}\n\n{user_prompt}"
                )
                logger.info("Successfully called Backboard add_message without model_name")
            except Exception as e:
                # If that fails, try with explicit model (like in backboard_client.py)
                logger.debug(f"Calling without model failed, trying with model: {e}")
                response = await backboard_client._sdk_client.add_message(
                    thread_id=thread_id,
                    content=f"{system_prompt}\n\n{user_prompt}",
                    llm_provider="openai",
                    model_name="gpt-4o-mini"
                )
                logger.info("Successfully called Backboard add_message with model")
        except Exception as e:
            # If add_message fails with validation error, the message was still sent
            # We need to wait and fetch the AI response from thread messages
            logger.warning(f"Backboard add_message failed, trying to get thread messages: {e}")
            import asyncio
            
            # Wait longer for AI to process (validation error means message was sent)
            await asyncio.sleep(4)  # Give AI more time to respond
            
            # Try to get messages from thread using multiple methods
            try:
                messages = None
                
                # Try different methods to get thread messages
                if hasattr(backboard_client._sdk_client, 'get_messages'):
                    messages = await backboard_client._sdk_client.get_messages(thread_id=thread_id)
                elif hasattr(backboard_client._sdk_client, 'list_messages'):
                    messages = await backboard_client._sdk_client.list_messages(thread_id=thread_id)
                elif hasattr(backboard_client._sdk_client, 'get_thread'):
                    thread_obj = await backboard_client._sdk_client.get_thread(thread_id=thread_id)
                    if hasattr(thread_obj, 'messages'):
                        messages = thread_obj.messages
                
                if messages:
                    # Handle different message formats
                    msg_list = []
                    if isinstance(messages, list):
                        msg_list = messages
                    elif hasattr(messages, 'messages'):
                        msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                    
                    # Find the latest assistant message (usually the last one)
                    for msg in reversed(msg_list):
                        # Check if this is an assistant message
                        is_assistant = False
                        if hasattr(msg, 'role'):
                            role = msg.role
                            # Handle enum or string
                            if hasattr(role, 'value'):
                                is_assistant = role.value in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role)
                            else:
                                is_assistant = str(role).lower() in ['assistant', 'ai', 'bot'] or 'ASSISTANT' in str(role).upper()
                        elif isinstance(msg, dict):
                            is_assistant = msg.get('role', '').lower() in ['assistant', 'ai', 'bot']
                        
                        # Get content
                        content = None
                        if hasattr(msg, 'content'):
                            content = msg.content
                        elif isinstance(msg, dict):
                            content = msg.get('content', '')
                        
                        if content and len(content) > 50:
                            # Check if it's an error message
                            content_lower = content.lower()
                            if ("llm error" not in content_lower and 
                                "api error" not in content_lower and 
                                "invalid model" not in content_lower):
                                # Prefer assistant messages, but take any substantial message if no role info
                                if is_assistant or not hasattr(msg, 'role'):
                                    response_text = content
                                    logger.info(f"Found AI response in thread messages (length: {len(response_text)}, role: {getattr(msg, 'role', 'unknown')})")
                                    break
            except Exception as fetch_error:
                logger.warning(f"Could not fetch thread messages: {fetch_error}")
                # Try one more time after a longer wait
                try:
                    await asyncio.sleep(3)
                    if hasattr(backboard_client._sdk_client, 'get_messages'):
                        messages = await backboard_client._sdk_client.get_messages(thread_id=thread_id)
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
        
        # Extract response text
        if response:
            if hasattr(response, 'content'):
                response_text = response.content
            elif isinstance(response, dict):
                response_text = response.get('content', '')
            else:
                response_text = str(response)
        
        if not response_text or len(response_text.strip()) == 0:
            logger.debug("Empty response from Backboard")
            return None
        
        # Check if response is an error
        if "llm error" in response_text.lower() or "api error" in response_text.lower() or "invalid model" in response_text.lower():
            logger.warning(f"Backboard returned error: {response_text[:200]}")
            return None
        
        logger.info(f"Backboard response for ticker {ticker} (first 500 chars): {response_text[:500]}")
        
        # Parse JSON from response
        try:
            # Try to extract JSON from markdown code blocks first
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
            else:
                # Try to find JSON object directly
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
            
            classification = json.loads(response_text)
            
            # Validate required fields
            required_fields = ['ticker', 'name', 'sector', 'market_cap', 'industry_risk']
            if all(k in classification for k in required_fields):
                # Check for error
                if 'error' in classification:
                    logger.warning(f"Backboard returned error for ticker {ticker}: {classification.get('error')}")
                    return None
                
                # Validate sector is one of our 11 sectors
                if classification['sector'] in valid_sectors:
                    # Ensure ticker matches
                    classification['ticker'] = ticker.upper()
                    return classification
                else:
                    logger.warning(f"Invalid sector '{classification['sector']}' for ticker {ticker}. Valid sectors: {valid_sectors}")
                    return None
            else:
                missing = [f for f in required_fields if f not in classification]
                logger.warning(f"Missing required fields for ticker {ticker}: {missing}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Backboard response for ticker {ticker}: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            return None
            
    except Exception as e:
        logger.debug(f"Error using Backboard for ticker {ticker}: {e}")
        return None


async def _classify_ticker_with_openai(ticker: str) -> Optional[Dict]:
    """
    Use OpenAI API directly to search and classify ticker.
    
    Returns classification dict or None if OpenAI is not available.
    """
    import os
    
    # Check if OpenAI API key is available
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.debug("OPENAI_API_KEY not set, skipping OpenAI classification")
        return None
    
    try:
        # Try to import openai
        try:
            import openai
        except ImportError:
            logger.debug("openai package not installed, skipping OpenAI classification")
            return None
        
        # Initialize OpenAI client
        client = openai.AsyncOpenAI(api_key=openai_api_key)
        
        # Get list of valid sectors for validation
        sectors_data = load_sectors_data()
        valid_sectors = [s['name'] for s in sectors_data['sectors']]
        sectors_list = ", ".join(valid_sectors)
        
        system_prompt = f"""You are a financial data classifier. Search the web for current information about stock tickers.

Return ONLY valid JSON with this exact structure:
{{
  "ticker": "{ticker}",
  "name": "Company Name",
  "sector": "One of: {sectors_list}",
  "market_cap": "large|medium|small|etf",
  "industry_risk": "low|medium|high|very_high"
}}

Valid sectors: {sectors_list}
Market cap: large (>$10B), medium ($2-10B), small (<$2B), etf (ETF/fund)
Industry risk: low, medium, high, very_high

If you cannot find the ticker, return: {{"error": "Ticker not found"}}"""
        
        user_prompt = f"""Search for current information about stock ticker: {ticker}

Extract and return ONLY JSON with:
1. Company name (full official name)
2. Sector (EXACTLY one of: {sectors_list})
3. Market cap: "large" (>$10B), "medium" ($2-10B), "small" (<$2B), or "etf"
4. Industry risk: "low", "medium", "high", or "very_high"

Example for AAPL:
{{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "market_cap": "large",
  "industry_risk": "medium"
}}

Return JSON only, no explanation."""
        
        # Call OpenAI with web search enabled (if available)
        try:
            # Try with gpt-4o which has web search capabilities
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"} if hasattr(openai, "types") else None
            )
        except Exception as e:
            # Fallback to gpt-4o-mini if gpt-4o not available
            logger.debug(f"gpt-4o not available, trying gpt-4o-mini: {e}")
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
        
        # Extract response
        response_text = response.choices[0].message.content
        
        # Parse JSON from response
        try:
            # Try to extract JSON from markdown code blocks first
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group(1)
            else:
                # Try to find JSON object directly
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
            
            classification = json.loads(response_text)
            
            # Validate required fields
            required_fields = ['ticker', 'name', 'sector', 'market_cap', 'industry_risk']
            if all(k in classification for k in required_fields):
                # Check for error
                if 'error' in classification:
                    logger.warning(f"OpenAI returned error for ticker {ticker}: {classification.get('error')}")
                    return None
                
                # Validate sector is one of our 11 sectors
                if classification['sector'] in valid_sectors:
                    # Ensure ticker matches
                    classification['ticker'] = ticker.upper()
                    return classification
                else:
                    logger.warning(f"Invalid sector '{classification['sector']}' for ticker {ticker}. Valid sectors: {valid_sectors}")
                    return None
            else:
                missing = [f for f in required_fields if f not in classification]
                logger.warning(f"Missing required fields for ticker {ticker}: {missing}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from OpenAI response for ticker {ticker}: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            return None
            
    except Exception as e:
        logger.debug(f"Error using OpenAI for ticker {ticker}: {e}")
        return None


async def _classify_ticker_with_web_search(ticker: str) -> Optional[Dict]:
    """
    Use web search and financial APIs to find ticker information and classify it.
    
    This is a fallback when OpenAI is not available.
    Uses multiple sources to gather company information.
    """
    import httpx
    
    ticker_upper = ticker.upper()
    sectors_data = load_sectors_data()
    valid_sectors = [s['name'] for s in sectors_data['sectors']]
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            company_name = None
            sector = None
            market_cap_str = None
            
            # Try Yahoo Finance profile page (scraping approach)
            try:
                # Get company profile from Yahoo Finance
                profile_url = f"https://finance.yahoo.com/quote/{ticker_upper}/profile"
                response = await client.get(profile_url, follow_redirects=True)
                
                if response.status_code == 200:
                    html = response.text
                    
                    # Extract company name
                    name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
                    if name_match:
                        company_name = name_match.group(1).strip()
                    
                    # Try to find sector in the HTML
                    # Yahoo Finance typically has sector info in the page
                    sector_match = re.search(r'Sector[^>]*>([^<]+)</span>', html, re.IGNORECASE)
                    if not sector_match:
                        sector_match = re.search(r'data-test="SECTOR-value"[^>]*>([^<]+)</td>', html, re.IGNORECASE)
                    if sector_match:
                        sector_raw = sector_match.group(1).strip()
                        # Map Yahoo Finance sectors to our sectors
                        sector = _map_yahoo_sector_to_our_sector(sector_raw, valid_sectors)
                    
                    # Try to get market cap info
                    market_cap_match = re.search(r'Market Cap[^>]*>([^<]+)</span>', html, re.IGNORECASE)
                    if market_cap_match:
                        market_cap_str = _classify_market_cap(market_cap_match.group(1))
                    
                    if company_name:
                        logger.info(f"Found company {company_name} for ticker {ticker_upper} from Yahoo Finance")
            except Exception as e:
                logger.debug(f"Yahoo Finance scraping failed for {ticker_upper}: {e}")
            
            # If we have enough info, return classification
            if company_name and sector:
                # Default values if not found
                market_cap = market_cap_str or "medium"
                industry_risk = "medium"  # Default, could be improved with more data
                
                return {
                    "ticker": ticker_upper,
                    "name": company_name,
                    "sector": sector,
                    "market_cap": market_cap,
                    "industry_risk": industry_risk
                }
            
            # Fallback: Try Alpha Vantage or other free APIs if available
            # For now, return None if we don't have enough info
            logger.warning(f"Insufficient information found for ticker {ticker_upper} via web search")
            return None
        
    except Exception as e:
        logger.debug(f"Error in web search for ticker {ticker_upper}: {e}")
        return None


def _map_yahoo_sector_to_our_sector(yahoo_sector: str, valid_sectors: List[str]) -> Optional[str]:
    """Map Yahoo Finance sector names to our sector names."""
    yahoo_lower = yahoo_sector.lower()
    
    # Mapping dictionary
    sector_mapping = {
        'technology': 'Technology',
        'tech': 'Technology',
        'healthcare': 'Healthcare',
        'health care': 'Healthcare',
        'financial services': 'Financial Services',
        'financial': 'Financial Services',
        'consumer discretionary': 'Consumer Discretionary',
        'consumer staples': 'Consumer Staples',
        'energy': 'Energy',
        'industrials': 'Industrials',
        'materials': 'Materials',
        'real estate': 'Real Estate',
        'utilities': 'Utilities',
        'communication services': 'Communication Services',
        'telecommunications': 'Communication Services',
    }
    
    # Try direct match
    for key, sector in sector_mapping.items():
        if key in yahoo_lower:
            if sector in valid_sectors:
                return sector
    
    # Try fuzzy matching
    for sector in valid_sectors:
        if sector.lower() in yahoo_lower or yahoo_lower in sector.lower():
            return sector
    
    return None


def _classify_market_cap(market_cap_str: str) -> str:
    """Classify market cap string into our categories."""
    import re
    
    # Extract number from string (e.g., "$100B" -> 100)
    match = re.search(r'([\d.]+)', market_cap_str.replace(',', ''))
    if not match:
        return "medium"
    
    try:
        value = float(match.group(1))
        # Determine unit (B for billions, M for millions, T for trillions)
        if 'T' in market_cap_str.upper():
            value *= 1000  # Convert trillions to billions
        elif 'M' in market_cap_str.upper():
            value /= 1000  # Convert millions to billions
        
        if value >= 10:
            return "large"
        elif value >= 2:
            return "medium"
        else:
            return "small"
    except (ValueError, AttributeError):
        return "medium"


async def _classify_ticker_with_ai(ticker: str, backboard_client) -> Optional[Dict]:
    """
    Use Backboard AI with web search to classify ticker.
    
    First searches the web for ticker information, then uses AI to extract structured info.
    """
    try:
        assistant_id = await backboard_client._ensure_assistant()
        if not assistant_id:
            return None
        
        # Get list of valid sectors for validation
        sectors_data = load_sectors_data()
        valid_sectors = [s['name'] for s in sectors_data['sectors']]
        sectors_list = ", ".join(valid_sectors)
        
        system_prompt = f"""You are a financial data classifier. You MUST search the web for current information about stock tickers.

CRITICAL: Use web search to find information about the ticker. Do not rely on training data only.

Return ONLY valid JSON with this exact structure:
{{
  "ticker": "{ticker}",
  "name": "Company Name",
  "sector": "One of: {sectors_list}",
  "market_cap": "large|medium|small|etf",
  "industry_risk": "low|medium|high|very_high"
}}

Valid sectors: {sectors_list}
Market cap: large (>$10B), medium ($2-10B), small (<$2B), etf (ETF/fund)
Industry risk: low, medium, high, very_high

If you cannot find the ticker after searching, return: {{"error": "Ticker not found"}}"""
        
        prompt = f"""SEARCH THE WEB for current information about stock ticker: {ticker}

After searching, extract and return ONLY JSON with:
1. Company name (full official name)
2. Sector (EXACTLY one of: {sectors_list})
3. Market cap: "large" (>$10B), "medium" ($2-10B), "small" (<$2B), or "etf"
4. Industry risk: "low", "medium", "high", or "very_high"

Example for AAPL:
{{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "market_cap": "large",
  "industry_risk": "medium"
}}

Return JSON only, no explanation."""
        
        # Use CHEAP model with web search enabled
        thread = await backboard_client._sdk_client.create_thread(assistant_id=assistant_id)
        
        # Get thread ID correctly
        thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
        
        # Create message with web search enabled (if supported by SDK)
        # Handle SDK validation errors gracefully
        response = None
        response_text = None
        raw_response_data = None
        
        # Try calling add_message - first without model (use assistant default), then with models
        # The assistant might have a default model configured
        response = None
        
        try:
            # Strategy 1: Try without model_name (use assistant's default)
            try:
                try:
                    # Try with web_search parameter if available
                    response = await backboard_client._sdk_client.add_message(
                        thread_id=thread_id,
                        content=f"{system_prompt}\n\n{prompt}",
                        web_search=True  # Enable web search
                    )
                    logger.info("Successfully called add_message without model_name (using assistant default)")
                except TypeError:
                    # If web_search parameter not supported, try without it
                    response = await backboard_client._sdk_client.add_message(
                        thread_id=thread_id,
                        content=f"{system_prompt}\n\n{prompt}"
                    )
                    logger.info("Successfully called add_message without model_name (no web_search)")
            except Exception as no_model_error:
                # If no model fails, try with explicit models
                error_str = str(no_model_error).lower()
                if "invalid model" in error_str or "model" in error_str:
                    logger.debug("Assistant default model not available, trying explicit models...")
                    
                    # Strategy 2: Try with explicit OpenAI models (if needed)
                    # Use standard OpenAI models that work with Backboard API
                    supported_models = [
                        "gpt-4o-mini",  # Standard cheap model
                        "gpt-4o",       # Fallback if mini not available
                    ]
                    
                    for supported_model in supported_models:
                        try:
                            try:
                                response = await backboard_client._sdk_client.add_message(
                                    thread_id=thread_id,
                                    content=f"{system_prompt}\n\n{prompt}",
                                    model_name=supported_model,
                                    web_search=True
                                )
                                logger.info(f"Successfully used model: {supported_model}")
                                break
                            except TypeError:
                                response = await backboard_client._sdk_client.add_message(
                                    thread_id=thread_id,
                                    content=f"{system_prompt}\n\n{prompt}",
                                    model_name=supported_model
                                )
                                logger.info(f"Successfully used model: {supported_model} (no web_search)")
                                break
                            except Exception as model_error:
                                error_str2 = str(model_error).lower()
                                if "invalid model" in error_str2 or "not supported" in error_str2:
                                    logger.debug(f"Model {supported_model} invalid, trying next...")
                                    continue
                                else:
                                    # Other error, might be validation - let it bubble up
                                    raise
                        except Exception:
                            # Continue to next model
                            continue
                    
                    # If all models failed, raise the original error
                    if not response:
                        raise no_model_error
                else:
                    # Other error (might be validation error), let it bubble up
                    raise
        except Exception as e:
            # SDK validation error - response format doesn't match expected model
            # The API returns 'message' but SDK expects 'latest_message'
            # Try to extract the actual response from the exception
            logger.warning(f"SDK validation error when calling add_message for {ticker}: {e}")
            
            # Try to extract response data from the exception
            # Pydantic validation errors may have the input value accessible
            try:
                # Check if exception has input_value attribute (Pydantic v2)
                if hasattr(e, 'input_value'):
                    raw_response_data = e.input_value
                    logger.info("Extracted response data from exception.input_value")
                elif hasattr(e, 'errors') and callable(e.errors):
                    # Try to get input from errors
                    errors = e.errors()
                    if errors and len(errors) > 0:
                        first_error = errors[0]
                        if 'input' in first_error:
                            raw_response_data = first_error['input']
                            logger.info("Extracted response data from exception.errors")
            except Exception as extract_error:
                logger.debug(f"Could not extract from exception attributes: {extract_error}")
            
            # Also try to extract from error string as fallback
            if not raw_response_data:
                error_str = str(e)
                if 'input_value' in error_str:
                    # Try to extract dict from error message (may be truncated)
                    try:
                        # Look for 'message' key in the error string
                        if "'message'" in error_str or '"message"' in error_str:
                            # The response has a 'message' field, try to extract it
                            # This is a fallback - the actual response might be truncated
                            logger.debug("Found 'message' in error string, but extraction may be incomplete")
                    except Exception:
                        pass
            
            # Wait for AI to process, then try to get messages from thread
            import asyncio
            await asyncio.sleep(3)  # Give AI more time to respond
            
            # Try to get messages from the thread using available methods
            if not response_text:
                logger.info("Trying to fetch thread messages to get AI response...")
                try:
                    # Try different methods to get thread messages
                    if hasattr(backboard_client._sdk_client, 'get_messages'):
                        messages = await backboard_client._sdk_client.get_messages(thread_id=thread_id)
                    elif hasattr(backboard_client._sdk_client, 'list_messages'):
                        messages = await backboard_client._sdk_client.list_messages(thread_id=thread_id)
                    elif hasattr(backboard_client._sdk_client, 'get_thread'):
                        thread_obj = await backboard_client._sdk_client.get_thread(thread_id=thread_id)
                        if hasattr(thread_obj, 'messages'):
                            messages = thread_obj.messages
                        else:
                            messages = None
                    else:
                        messages = None
                        logger.warning("No method found to retrieve thread messages from SDK")
                    
                    # Find the latest AI/assistant message (not user or system messages)
                    if messages:
                        # Messages might be in different formats
                        if isinstance(messages, list):
                            # Find the most recent assistant/AI message
                            for msg in reversed(messages):
                                # Check if this is an assistant/AI message (not user or system)
                                is_assistant = False
                                if hasattr(msg, 'role'):
                                    is_assistant = msg.role in ['assistant', 'ai', 'bot']
                                elif isinstance(msg, dict):
                                    is_assistant = msg.get('role') in ['assistant', 'ai', 'bot'] or msg.get('type') == 'assistant'
                                
                                # Also check if content exists and is substantial (not just "Message added successfully")
                                content = None
                                if hasattr(msg, 'content'):
                                    content = msg.content
                                elif isinstance(msg, dict) and 'content' in msg:
                                    content = msg['content']
                                
                                if content and len(content) > 50:  # Substantial content
                                    # If we found role info, prefer assistant messages
                                    # Otherwise, take any substantial message (likely the AI response)
                                    if is_assistant or not hasattr(msg, 'role'):
                                        response_text = content
                                        response = msg
                                        logger.info(f"Found AI response in thread messages (length: {len(response_text)}, role: {getattr(msg, 'role', 'unknown') if hasattr(msg, 'role') else msg.get('role', 'unknown')})")
                                        break
                        elif hasattr(messages, 'messages'):
                            # Messages object with messages attribute
                            msg_list = messages.messages if isinstance(messages.messages, list) else [messages.messages]
                            for msg in reversed(msg_list):
                                # Check if this is an assistant message
                                is_assistant = False
                                if hasattr(msg, 'role'):
                                    is_assistant = msg.role in ['assistant', 'ai', 'bot']
                                elif isinstance(msg, dict):
                                    is_assistant = msg.get('role') in ['assistant', 'ai', 'bot']
                                
                                content = None
                                if hasattr(msg, 'content'):
                                    content = msg.content
                                elif isinstance(msg, dict) and 'content' in msg:
                                    content = msg['content']
                                
                                if content and len(content) > 50:
                                    if is_assistant or not hasattr(msg, 'role'):
                                        response_text = content
                                        response = msg
                                        break
                except Exception as fetch_error:
                    logger.warning(f"Could not fetch thread messages: {fetch_error}")
        
        # Extract response - handle different response formats
        # Initialize response_text if not already set
        if response_text is None:
            response_text = ""
        
        # Log current state before extracting from raw_response_data
        if response_text:
            logger.info(f"Already have response_text from thread messages (length: {len(response_text)}), skipping raw_response_data extraction")
        
        # If we extracted raw response data from error, parse it
        # Only use this if we don't already have a response from thread messages
        # Check both None and empty string to be safe
        if (not response_text or len(response_text.strip()) == 0) and raw_response_data and isinstance(raw_response_data, dict):
            # The response is already a dict, extract content directly
            try:
                # Look for message content in various locations
                # Note: The 'message' field might just be a confirmation, not the AI response
                # The actual AI response is likely in thread messages, which we already tried above
                if 'message' in raw_response_data:
                    msg = raw_response_data['message']
                    if isinstance(msg, dict):
                        # Message is a dict, look for content
                        if 'content' in msg:
                            content = msg['content']
                            # Skip if it's just a confirmation message
                            if len(content) > 50 and 'successfully' not in content.lower():
                                response_text = content
                        elif 'text' in msg:
                            content = msg['text']
                            if len(content) > 50 and 'successfully' not in content.lower():
                                response_text = content
                        elif 'body' in msg:
                            content = msg['body']
                            if len(content) > 50 and 'successfully' not in content.lower():
                                response_text = content
                        else:
                            # Try to find any substantial string value in the message dict
                            for key, value in msg.items():
                                if isinstance(value, str) and len(value) > 50 and 'successfully' not in value.lower():
                                    response_text = value
                                    break
                    elif isinstance(msg, str) and len(msg) > 50 and 'successfully' not in msg.lower():
                        response_text = msg
                elif 'content' in raw_response_data:
                    content = raw_response_data['content']
                    if len(content) > 50 and 'successfully' not in content.lower():
                        response_text = content
                elif 'text' in raw_response_data:
                    content = raw_response_data['text']
                    if len(content) > 50 and 'successfully' not in content.lower():
                        response_text = content
                
                if response_text:
                    logger.info(f"Extracted response text from raw_response_data (length: {len(response_text)})")
            except Exception as e:
                logger.warning(f"Error parsing raw response data: {e}")
                logger.warning(f"Response data structure: {type(raw_response_data)} - {str(raw_response_data)[:200]}")
        
        # If we have a valid response object, extract from it
        if response and not response_text:
            if hasattr(response, 'content'):
                response_text = response.content
            elif isinstance(response, dict):
                response_text = response.get('content', '') or response.get('text', '') or str(response)
            elif hasattr(response, 'text'):
                response_text = response.text
            elif hasattr(response, 'message') and hasattr(response.message, 'content'):
                response_text = response.message.content
            else:
                response_text = str(response)
        
        if not response_text or len(response_text.strip()) == 0:
            logger.error(f"Empty response from AI for ticker {ticker}")
            logger.error(f"Response object type: {type(response)}")
            logger.error(f"Response object: {response}")
            return None
        
        # Check if the response is an error message from the LLM API
        response_lower = response_text.lower()
        if "llm error" in response_lower or "api error" in response_lower or "invalid model" in response_lower:
            logger.error(f"LLM API error in response for ticker {ticker}: {response_text[:200]}")
            logger.error("This usually means the assistant is not configured with a valid model.")
            logger.error("Please configure the assistant in Backboard dashboard with a supported model.")
            return None
        
        logger.info(f"AI response for ticker {ticker} (first 500 chars): {response_text[:500]}")
        
        # Parse JSON from response
        # Try to extract JSON from markdown code blocks first
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if not json_match:
            # Try to find JSON object directly (multiline)
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
        
        if json_match:
            try:
                classification = json.loads(json_match.group(0) if isinstance(json_match, re.Match) else json_match.group(0))
                
                # Validate required fields
                required_fields = ['ticker', 'name', 'sector', 'market_cap', 'industry_risk']
                if all(k in classification for k in required_fields):
                    # Validate sector is one of our 11 sectors
                    if classification['sector'] in valid_sectors:
                        # Ensure ticker matches
                        classification['ticker'] = ticker.upper()
                        return classification
                    else:
                        logger.warning(f"Invalid sector '{classification['sector']}' for ticker {ticker}. Valid sectors: {valid_sectors}")
                        return None
                else:
                    missing = [f for f in required_fields if f not in classification]
                    logger.warning(f"Missing required fields for ticker {ticker}: {missing}")
                    return None
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON for ticker {ticker}: {e}")
                logger.error(f"Response text: {response_text[:500]}")
                return None
        else:
            logger.warning(f"No JSON found in AI response for ticker {ticker}")
            logger.warning(f"Full response: {response_text[:500]}")
            # Try one more time with a simpler regex
            simple_json = re.search(r'\{[^}]+\}', response_text)
            if simple_json:
                try:
                    classification = json.loads(simple_json.group(0))
                    if all(k in classification for k in ['ticker', 'name', 'sector', 'market_cap', 'industry_risk']):
                        if classification['sector'] in valid_sectors:
                            classification['ticker'] = ticker.upper()
                            logger.info(f"Successfully parsed with simple regex")
                            return classification
                except:
                    pass
            return None
        
    except Exception as e:
        logger.error(f"Error classifying ticker with AI: {e}", exc_info=True)
        return None


def add_ticker_to_database(classification: Dict) -> bool:
    """
    Add ticker to sectors.json database.
    
    Args:
        classification: Dict with ticker, name, sector, market_cap, industry_risk
        
    Returns:
        True if added successfully, False otherwise
    """
    try:
        # Load current data
        data = load_sectors_data()
        
        # Find the sector
        sector_name = classification['sector']
        sector_found = None
        for sector in data['sectors']:
            if sector['name'] == sector_name:
                sector_found = sector
                break
        
        if not sector_found:
            logger.error(f"Sector '{sector_name}' not found in database")
            return False
        
        # Check if ticker already exists
        ticker_upper = classification['ticker'].upper()
        for stock in sector_found['stocks']:
            if stock['ticker'].upper() == ticker_upper:
                logger.info(f"Ticker {ticker_upper} already exists in database")
                return True
        
        # Add stock to sector
        new_stock = {
            "ticker": classification['ticker'].upper(),
            "name": classification['name'],
            "market_cap": classification['market_cap'],
            "industry_risk": classification['industry_risk']
        }
        
        sector_found['stocks'].append(new_stock)
        
        # Save to file
        with open(SECTORS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Added ticker {ticker_upper} to {sector_name} sector")
        return True
        
    except Exception as e:
        logger.error(f"Error adding ticker to database: {e}", exc_info=True)
        return False


async def lookup_or_add_ticker(ticker: str) -> Tuple[bool, Optional[str]]:
    """
    Lookup ticker in database, or search web and add if found.
    
    Returns:
        (success: bool, message: str)
        - (True, "Found in database") if already exists
        - (True, "Added to database") if successfully added
        - (False, "No match found") if cannot find/classify
        - (False, error_message) if error occurred
    """
    ticker_upper = ticker.upper()
    
    # Check if already in database
    if ticker_exists(ticker_upper):
        return True, "Found in database"
    
    # Search and classify
    logger.info(f"Ticker {ticker_upper} not found in database, searching web...")
    classification = None
    try:
        classification = await search_and_classify_ticker(ticker_upper)
        
        if not classification:
            logger.warning(f"Could not classify ticker {ticker_upper} - AI returned no valid classification")
            # Check server logs for the actual AI response
            return False, "No match found - unable to classify ticker from web search. Check server logs for AI response details."
    except Exception as e:
        logger.error(f"Error during ticker classification for {ticker_upper}: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False, f"Error during web search: {str(e)}"
    
    if not classification:
        return False, "No match found - unable to classify ticker from web search"
    
    # Add to database
    if add_ticker_to_database(classification):
        return True, f"Added to database (classified as {classification['sector']})"
    else:
        return False, "Failed to add ticker to database"

