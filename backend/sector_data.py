"""Sector and stock data loader."""

import json
from pathlib import Path
from typing import Optional, Dict, List
from functools import lru_cache
import os

# Load sectors data
SECTORS_FILE = Path(__file__).parent.parent / "data" / "sectors.json"

# Cache for sectors data
_sectors_data_cache: Optional[Dict] = None
_sectors_file_mtime: Optional[float] = None


def load_sectors_data() -> Dict:
    """Load sectors data from JSON file with in-memory caching.
    
    Reloads from file if file modification time changes.
    """
    global _sectors_data_cache, _sectors_file_mtime
    
    # Check if file exists
    if not SECTORS_FILE.exists():
        raise FileNotFoundError(f"Sectors file not found: {SECTORS_FILE}")
    
    # Get current file modification time
    current_mtime = os.path.getmtime(SECTORS_FILE)
    
    # Reload if cache is None or file was modified
    if _sectors_data_cache is None or _sectors_file_mtime != current_mtime:
        try:
            with open(SECTORS_FILE, 'r') as f:
                _sectors_data_cache = json.load(f)
            _sectors_file_mtime = current_mtime
            
            # Validate structure
            if not isinstance(_sectors_data_cache, dict):
                raise ValueError("Invalid sectors.json: root must be a dictionary")
            if 'sectors' not in _sectors_data_cache:
                raise ValueError("Invalid sectors.json: missing 'sectors' key")
            if not isinstance(_sectors_data_cache['sectors'], list):
                raise ValueError("Invalid sectors.json: 'sectors' must be a list")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in sectors.json: {e}")
        except Exception as e:
            raise ValueError(f"Error loading sectors.json: {e}")
    
    return _sectors_data_cache


def clear_sectors_cache():
    """Clear the sectors data cache (useful for testing or forced reload)."""
    global _sectors_data_cache, _sectors_file_mtime
    _sectors_data_cache = None
    _sectors_file_mtime = None


def get_sector_by_keyword(keyword: str) -> Optional[Dict]:
    """Find sector by keyword match."""
    data = load_sectors_data()
    keyword_lower = keyword.lower()
    
    for sector in data['sectors']:
        if keyword_lower in sector['name'].lower():
            return sector
        for kw in sector['keywords']:
            if keyword_lower in kw.lower() or kw.lower() in keyword_lower:
                return sector
    return None


def get_sectors_by_keywords(text: str) -> List[Dict]:
    """Extract multiple sectors from text based on keywords."""
    import re
    data = load_sectors_data()
    text_lower = text.lower()
    found_sectors = []
    seen_names = set()
    
    # Note: Sector keywords from sectors.json will be matched below
    # No hardcoded alias mappings - everything goes through keyword matching
    
    # Then check sector names and keywords (but skip if already found via alias)
    for sector in data['sectors']:
        if sector['name'] in seen_names:
            continue
            
        # Check if sector name appears in text (as whole word)
        sector_name_lower = sector['name'].lower()
        if re.search(rf'\b{sector_name_lower}\b', text_lower):
            found_sectors.append(sector)
            seen_names.add(sector['name'])
            continue
            
        # Check keywords (prefer whole word matches)
        for keyword in sector['keywords']:
            keyword_lower = keyword.lower()
            # Use word boundary for multi-word keywords, otherwise substring
            if ' ' in keyword_lower:
                if keyword_lower in text_lower:
                    found_sectors.append(sector)
                    seen_names.add(sector['name'])
                    break
            else:
                # Single word - use word boundary to avoid substring matches
                if re.search(rf'\b{re.escape(keyword_lower)}\b', text_lower):
                    found_sectors.append(sector)
                    seen_names.add(sector['name'])
                    break
    
    return found_sectors


def get_stocks_for_sectors(sector_names: List[str]) -> List[Dict]:
    """Get all stocks from specified sectors."""
    data = load_sectors_data()
    stocks = []
    seen_tickers = set()
    
    for sector in data['sectors']:
        if sector['name'] in sector_names:
            for stock in sector['stocks']:
                if stock['ticker'] not in seen_tickers:
                    stocks.append(stock)
                    seen_tickers.add(stock['ticker'])
                    # Add sector name to stock info
                    stock_with_sector = stock.copy()
                    stock_with_sector['sector'] = sector['name']
                    stocks[-1] = stock_with_sector
    
    return stocks


def get_risk_score_for_stock(ticker: str) -> Optional[int]:
    """Get combined risk score for a stock based on market cap and industry risk."""
    data = load_sectors_data()
    
    for sector in data['sectors']:
        for stock in sector['stocks']:
            if stock['ticker'].upper() == ticker.upper():
                # Get industry risk score
                industry_risk = stock.get('industry_risk', 'medium')
                risk_scores = data['risk_levels']
                base_risk = risk_scores.get(industry_risk, risk_scores['medium'])['score']
                
                # Apply market cap multiplier
                market_cap = stock.get('market_cap', 'large')
                cap_multipliers = data['market_cap_categories']
                multiplier = cap_multipliers.get(market_cap, cap_multipliers['large'])['risk_multiplier']
                
                # Calculate final risk (1-100 scale, roughly)
                final_risk = int(base_risk * multiplier * 20)  # Scale to ~1-100
                return min(max(final_risk, 1), 100)
    
    return None


def get_all_tickers() -> List[str]:
    """Get list of all tickers across all sectors."""
    data = load_sectors_data()
    tickers = []
    
    for sector in data['sectors']:
        for stock in sector['stocks']:
            tickers.append(stock['ticker'])
    
    return sorted(list(set(tickers)))


def validate_ticker_in_sectors(ticker: str, allowed_sectors: List[str]) -> bool:
    """Check if ticker belongs to allowed sectors."""
    if not allowed_sectors:
        return True  # No restriction
    
    data = load_sectors_data()
    ticker_upper = ticker.upper()
    
    for sector in data['sectors']:
        if sector['name'] in allowed_sectors:
            for stock in sector['stocks']:
                if stock['ticker'].upper() == ticker_upper:
                    return True
    
    return False


def get_ticker_sector(ticker: str) -> Optional[str]:
    """Get the sector name for a given ticker."""
    data = load_sectors_data()
    ticker_upper = ticker.upper()
    
    for sector in data['sectors']:
        for stock in sector['stocks']:
            if stock['ticker'].upper() == ticker_upper:
                return sector['name']
    
    return None

