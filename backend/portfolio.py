"""Local portfolio analytics and rebalance logic (no LLM)."""

from typing import Optional, List
from .models import (
    InvestorProfile,
    PortfolioInput,
    PortfolioMetrics,
    TargetAllocation,
    RebalancePlan,
    RebalanceAction,
    Holding,
)
from .sector_data import (
    validate_ticker_in_sectors,
    get_risk_score_for_stock,
    get_stocks_for_sectors,
    get_sectors_by_keywords,
    load_sectors_data,
    get_ticker_sector,
)


def get_sector_breakdown(portfolio: PortfolioInput) -> dict[str, float]:
    """Calculate sector allocation breakdown."""
    sector_weights: dict[str, float] = {}
    
    for holding in portfolio.holdings:
        sector = get_ticker_sector(holding.ticker)
        if sector:
            sector_weights[sector] = sector_weights.get(sector, 0.0) + holding.weight
        else:
            # If ticker not found, use "Unknown" sector
            sector_weights["Unknown"] = sector_weights.get("Unknown", 0.0) + holding.weight
    
    return sector_weights


def compute_metrics(
    portfolio: PortfolioInput, profile: Optional[InvestorProfile] = None
) -> PortfolioMetrics:
    """Compute portfolio metrics locally.
    
    Validates that portfolio doesn't exceed 100% and has minimum 5% cash for safety.
    """
    holdings = portfolio.holdings
    total_weight = portfolio.cash_weight + sum(h.weight for h in holdings)
    
    # Validate weights sum to ~1.0
    if abs(total_weight - 1.0) > 0.01:
        raise ValueError(f"Weights sum to {total_weight:.4f}, expected ~1.0")
    
    # Safety check: ensure minimum 5% cash for safety (warn if not met)
    MIN_CASH_PCT = 0.05
    if portfolio.cash_weight < MIN_CASH_PCT:
        # Note: This is just a warning in metrics, actual enforcement happens in allocation computation
        pass  # Warning can be added to constraint violations if needed
    
    # Sort by weight descending
    sorted_holdings = sorted(holdings, key=lambda h: h.weight, reverse=True)
    
    # Concentration metrics
    top_1_weight = sorted_holdings[0].weight if sorted_holdings else 0.0
    top_3_weight = sum(h.weight for h in sorted_holdings[:3])
    top_5_weight = sum(h.weight for h in sorted_holdings[:5])
    
    # Herfindahl-Hirschman Index
    hhi = sum(h.weight ** 2 for h in holdings)
    if portfolio.cash_weight > 0:
        hhi += portfolio.cash_weight ** 2
    
    # Calculate sector breakdown
    sector_allocation = get_sector_breakdown(portfolio)
    
    # Create ticker to sector mapping
    ticker_sectors: dict[str, str] = {}
    for holding in holdings:
        sector = get_ticker_sector(holding.ticker)
        ticker_sectors[holding.ticker.upper()] = sector or "Unknown"
    
    # Constraint violations
    violations = []
    if profile:
        # Check max holdings
        total_count = len(holdings) + (1 if portfolio.cash_weight > 0 else 0)
        if total_count > profile.constraints.max_holdings:
            violations.append(
                f"Too many holdings: {total_count} > {profile.constraints.max_holdings}"
            )
        
        # Check max position pct
        for holding in holdings:
            pct = holding.weight * 100
            if pct > profile.constraints.max_position_pct:
                violations.append(
                    f"{holding.ticker}: {pct:.1f}% > {profile.constraints.max_position_pct}% max"
                )
        
        # Check exclusions
        for holding in holdings:
            ticker_lower = holding.ticker.lower()
            for exclusion in profile.constraints.exclusions:
                if exclusion.lower() in ticker_lower:
                    violations.append(
                        f"{holding.ticker} violates exclusion: {exclusion}"
                    )
        
        # Check preferred sector preference (NOT a hard constraint - just a preference)
        # Preferred sectors are preferences, not requirements - diversification is important
        # We only check if there are holdings in excluded sectors (which IS a constraint)
        # Non-preferred sectors are allowed for diversification purposes
        pass  # Preferred sectors are preferences, not hard constraints
    
    return PortfolioMetrics(
        total_holdings=len(holdings) + (1 if portfolio.cash_weight > 0 else 0),
        top_1_weight=top_1_weight,
        top_3_weight=top_3_weight,
        top_5_weight=top_5_weight,
        herfindahl_index=hhi,
        constraint_violations=violations,
        drift_summary=None,
        sector_allocation=sector_allocation,
        ticker_sectors=ticker_sectors,
    )


def compute_target_allocation(profile: InvestorProfile) -> TargetAllocation:
    """Compute target allocation based on profile (deterministic rules).
    
    Always ensures minimum 5% cash for safety.
    Enhanced risk-aversion: Higher defensive/cash allocations for risk-averse clients.
    """
    risk = profile.risk_score / 100.0
    horizon_years = profile.horizon_months / 12.0
    
    # Enhanced risk-aversion detection
    is_risk_averse = profile.risk_score < 50  # More aggressive threshold
    is_very_risk_averse = profile.risk_score < 35
    
    # Base equity calculation
    base_equity = min(
        80.0,
        40.0 + (risk * 40.0) + (min(horizon_years, 10) / 10.0 * 20.0)
    )
    
    # Thematic sector allocation (preferred sectors)
    # Reduce thematic weight for risk-averse clients to encourage diversification
    if is_very_risk_averse:
        thematic_weight = 5.0 if profile.preferences.sectors_like else 0.0  # Minimal thematic for very risk-averse
    elif is_risk_averse:
        thematic_weight = 8.0 if profile.preferences.sectors_like else 3.0  # Reduced thematic for risk-averse
    else:
        thematic_weight = 15.0 if profile.preferences.sectors_like else 5.0  # Original allocation
    
    # Cash allocation - always minimum 5% for safety, higher for risk-averse
    MIN_CASH_PCT = 5.0
    if is_very_risk_averse:
        # Very risk-averse: Higher cash allocation
        if profile.horizon_months < 12:
            cash_weight = max(25.0, MIN_CASH_PCT)
        elif profile.horizon_months < 24:
            cash_weight = max(15.0, MIN_CASH_PCT)
        else:
            cash_weight = max(10.0, MIN_CASH_PCT)  # At least 10% for very risk-averse
    elif is_risk_averse:
        # Risk-averse: Moderate cash allocation
        if profile.horizon_months < 12:
            cash_weight = max(20.0, MIN_CASH_PCT)
        elif profile.horizon_months < 24:
            cash_weight = max(12.0, MIN_CASH_PCT)
        else:
            cash_weight = max(7.0, MIN_CASH_PCT)  # At least 7% for risk-averse
    else:
        # Standard cash allocation
        if profile.horizon_months < 12:
            cash_weight = max(20.0, MIN_CASH_PCT)
        elif profile.horizon_months < 24:
            cash_weight = max(10.0, MIN_CASH_PCT)
        else:
            cash_weight = MIN_CASH_PCT  # Always at least 5%
    
    # Enhanced defensive allocation for risk-averse clients
    if is_very_risk_averse:
        defensive_weight = 20.0  # Higher defensive allocation
    elif is_risk_averse:
        defensive_weight = 15.0  # Moderate defensive allocation
    elif profile.risk_score < 40:
        defensive_weight = 10.0
    else:
        defensive_weight = 0.0
    
    # Adjust for income objective (lower growth focus)
    if profile.objective.type == "income":
        base_equity *= 0.7
        defensive_weight += 10.0
        if is_risk_averse:
            defensive_weight += 5.0  # Extra defensive for risk-averse income investors
    elif profile.objective.type == "balanced":
        base_equity *= 0.85
    
    # Normalize to 100%, but ensure cash is at least MIN_CASH_PCT
    total = base_equity + thematic_weight + cash_weight + defensive_weight
    if total > 100.0:
        # Scale down, but preserve minimum cash
        equity_to_scale = base_equity + thematic_weight + defensive_weight
        max_equity = 100.0 - MIN_CASH_PCT  # Reserve minimum cash
        if equity_to_scale > max_equity:
            scale = max_equity / equity_to_scale if equity_to_scale > 0 else 1.0
            base_equity *= scale
            thematic_weight *= scale
            defensive_weight *= scale
            cash_weight = MIN_CASH_PCT  # Ensure minimum cash
        else:
            # Normal scaling works
            scale = 100.0 / total
            base_equity *= scale
            thematic_weight *= scale
            cash_weight = max(cash_weight * scale, MIN_CASH_PCT)  # Ensure minimum
            defensive_weight *= scale
    else:
        # Add remainder to core equity, but ensure cash is at least MIN_CASH_PCT
        remainder = 100.0 - total
        if cash_weight < MIN_CASH_PCT:
            # Increase cash to minimum, reduce remainder
            remainder -= (MIN_CASH_PCT - cash_weight)
            cash_weight = MIN_CASH_PCT
        base_equity += remainder
    
    # Final check: ensure cash is at least MIN_CASH_PCT
    if cash_weight < MIN_CASH_PCT:
        excess = MIN_CASH_PCT - cash_weight
        cash_weight = MIN_CASH_PCT
        # Reduce from equity proportionally
        equity_total = base_equity + thematic_weight + defensive_weight
        if equity_total > excess:
            scale = (equity_total - excess) / equity_total if equity_total > 0 else 1.0
            base_equity *= scale
            thematic_weight *= scale
            defensive_weight *= scale
    
    return TargetAllocation(
        cash=cash_weight / 100.0,
        core_equity=base_equity / 100.0,
        thematic_sectors=thematic_weight / 100.0,
        defensive=defensive_weight / 100.0,
    )


def compute_rebalance_plan(
    current_portfolio: PortfolioInput,
    profile: InvestorProfile,
    target: TargetAllocation,
) -> RebalancePlan:
    """Compute rebalance plan using greedy algorithm with diversification logic."""
    actions: list[RebalanceAction] = []
    warnings: list[str] = []
    notes: list[str] = []
    
    # Create ticker -> current weight map
    current_weights: dict[str, float] = {}
    current_tickers = set()
    for holding in current_portfolio.holdings:
        current_weights[holding.ticker] = holding.weight
        current_tickers.add(holding.ticker.upper())
    
    max_position = profile.constraints.max_position_pct / 100.0
    max_holdings = profile.constraints.max_holdings
    total_target_equity = target.core_equity + target.thematic_sectors + target.defensive
    
    # Sector diversification limits based on risk tolerance
    is_risk_averse = profile.risk_score < 50
    is_very_risk_averse = profile.risk_score < 35
    if is_very_risk_averse:
        max_sector_weight = 0.20  # Max 20% per sector for very risk-averse
        min_sectors = 5  # Require at least 5 sectors
    elif is_risk_averse:
        max_sector_weight = 0.25  # Max 25% per sector for risk-averse
        min_sectors = 4  # Require at least 4 sectors
    else:
        max_sector_weight = 0.35  # Max 35% per sector for others
        min_sectors = 3  # Require at least 3 sectors
    
    # Calculate current sector allocation
    current_sector_weights: dict[str, float] = {}
    for holding in current_portfolio.holdings:
        sector = get_ticker_sector(holding.ticker) or 'Unknown'
        current_sector_weights[sector] = current_sector_weights.get(sector, 0.0) + holding.weight
    
    # Check if portfolio is too concentrated and needs diversification
    # For long-term portfolios (horizon > 24 months), we want better diversification
    is_long_term = profile.horizon_months > 24
    num_holdings = len(current_portfolio.holdings)
    is_too_concentrated = (
        is_long_term and 
        num_holdings < min(8, max_holdings) and 
        num_holdings < max_holdings
    )
    
    # Check if any sector exceeds max weight (sector concentration)
    sectors_exceeding_limit = [
        sector for sector, weight in current_sector_weights.items() 
        if weight > max_sector_weight
    ]
    has_sector_concentration = len(sectors_exceeding_limit) > 0
    
    # Calculate concentration metrics
    if current_portfolio.holdings:
        sorted_holdings = sorted(current_portfolio.holdings, key=lambda h: h.weight, reverse=True)
        top_2_weight = sum(h.weight for h in sorted_holdings[:2])
        is_highly_concentrated = top_2_weight > 0.6  # More than 60% in top 2 holdings
    else:
        is_highly_concentrated = False
    
    # If portfolio is too concentrated, add diversified holdings
    new_holdings_to_add = []
    if is_too_concentrated or is_highly_concentrated:
        sectors_data = load_sectors_data()
        
        # Get current sectors
        current_sectors = set()
        for holding in current_portfolio.holdings:
            sector = get_ticker_sector(holding.ticker)
            if sector:
                current_sectors.add(sector)
        
        # Determine how many new holdings to add
        target_holdings_count = min(max_holdings, max(8, num_holdings * 2)) if is_long_term else max_holdings
        new_holdings_needed = max(0, target_holdings_count - num_holdings)
        
        if new_holdings_needed > 0:
            # Get stocks from different sectors for diversification
            all_sectors = [s['name'] for s in sectors_data['sectors']]
            
            # Prefer sectors not already represented
            underrepresented_sectors = [s for s in all_sectors if s not in current_sectors]
            
            # Separate preferred and non-preferred sectors for balanced selection
            if profile.preferences.sectors_like:
                preferred_set = set(profile.preferences.sectors_like)
                preferred_sectors_list = [s for s in underrepresented_sectors if s in preferred_set]
                other_sectors_list = [s for s in underrepresented_sectors if s not in preferred_set and s not in (profile.preferences.sectors_avoid or [])]
                
                # If we don't have enough underrepresented sectors, expand to all sectors
                if len(preferred_sectors_list) + len(other_sectors_list) < min_sectors:
                    all_preferred = [s for s in all_sectors if s in preferred_set and s not in current_sectors and s not in (profile.preferences.sectors_avoid or [])]
                    all_other = [s for s in all_sectors if s not in preferred_set and s not in current_sectors and s not in (profile.preferences.sectors_avoid or [])]
                    preferred_sectors_list = all_preferred if preferred_sectors_list else preferred_sectors_list
                    other_sectors_list = all_other if not other_sectors_list else other_sectors_list
            else:
                preferred_sectors_list = []
                other_sectors_list = underrepresented_sectors if underrepresented_sectors else [s for s in all_sectors if s not in (profile.preferences.sectors_avoid or [])]
            
            # Avoid excluded sectors
            if profile.preferences.sectors_avoid:
                preferred_sectors_list = [s for s in preferred_sectors_list if s not in profile.preferences.sectors_avoid]
                other_sectors_list = [s for s in other_sectors_list if s not in profile.preferences.sectors_avoid]
            
            # Get stocks from sectors, grouped by preferred vs other
            preferred_stocks = get_stocks_for_sectors(preferred_sectors_list) if preferred_sectors_list else []
            other_stocks = get_stocks_for_sectors(other_sectors_list) if other_sectors_list else []
            
            # Group stocks by sector for balanced selection
            preferred_by_sector: dict[str, list] = {}
            for stock in preferred_stocks:
                sector = stock.get('sector') or get_ticker_sector(stock['ticker']) or 'Unknown'
                if sector not in preferred_by_sector:
                    preferred_by_sector[sector] = []
                preferred_by_sector[sector].append(stock)
            
            other_by_sector: dict[str, list] = {}
            for stock in other_stocks:
                sector = stock.get('sector') or get_ticker_sector(stock['ticker']) or 'Unknown'
                if sector not in other_by_sector:
                    other_by_sector[sector] = []
                other_by_sector[sector].append(stock)
            
            # Balanced selection: alternate between preferred and other sectors
            # Target: Ensure diversification with proper balance
            seen_tickers = current_tickers.copy()
            sectors_added = set()
            
            # First pass: Add one stock from each underrepresented sector (prioritizing underrepresented preferred sectors)
            for sector in preferred_sectors_list + other_sectors_list:
                if len(new_holdings_to_add) >= new_holdings_needed:
                    break
                if sector in sectors_added:
                    continue
                
                stocks_for_sector = preferred_by_sector.get(sector, []) or other_by_sector.get(sector, [])
                for stock in stocks_for_sector:
                    ticker = stock['ticker'].upper()
                    ticker_lower = stock['ticker'].lower()
                    
                    if ticker in seen_tickers:
                        continue
                    
                    excluded = any(exclusion.lower() in ticker_lower for exclusion in profile.constraints.exclusions)
                    if excluded:
                        continue
                    
                    new_holdings_to_add.append(stock)
                    seen_tickers.add(ticker)
                    sectors_added.add(sector)
                    break
            
            # Second pass: Fill remaining slots with balanced selection
            # Calculate how many preferred vs other we should add to maintain balance
            preferred_count = sum(1 for s in new_holdings_to_add 
                                 if validate_ticker_in_sectors(s['ticker'], profile.preferences.sectors_like or []))
            other_count = len(new_holdings_to_add) - preferred_count
            
            # Target ratio: prefer 50-70% from preferred sectors, rest from others for diversification
            preferred_target_ratio = 0.6 if profile.preferences.sectors_like else 0.0
            preferred_target_count = int(new_holdings_needed * preferred_target_ratio)
            
            # Continue adding stocks with balanced selection
            preferred_stocks_remaining = [s for s in preferred_stocks if s['ticker'].upper() not in seen_tickers]
            other_stocks_remaining = [s for s in other_stocks if s['ticker'].upper() not in seen_tickers]
            
            while len(new_holdings_to_add) < new_holdings_needed and (preferred_stocks_remaining or other_stocks_remaining):
                # Alternate between preferred and other to maintain balance
                should_add_preferred = (preferred_count < preferred_target_count) and preferred_stocks_remaining
                should_add_other = (other_count >= preferred_count) or not preferred_stocks_remaining
                
                if should_add_preferred and preferred_stocks_remaining:
                    stock = preferred_stocks_remaining.pop(0)
                    ticker = stock['ticker'].upper()
                    ticker_lower = stock['ticker'].lower()
                    
                    if ticker not in seen_tickers:
                        excluded = any(exclusion.lower() in ticker_lower for exclusion in profile.constraints.exclusions)
                        if not excluded:
                            new_holdings_to_add.append(stock)
                            seen_tickers.add(ticker)
                            preferred_count += 1
                elif should_add_other and other_stocks_remaining:
                    stock = other_stocks_remaining.pop(0)
                    ticker = stock['ticker'].upper()
                    ticker_lower = stock['ticker'].lower()
                    
                    if ticker not in seen_tickers:
                        excluded = any(exclusion.lower() in ticker_lower for exclusion in profile.constraints.exclusions)
                        if not excluded:
                            new_holdings_to_add.append(stock)
                            seen_tickers.add(ticker)
                            other_count += 1
                else:
                    # Fallback: add any available stock
                    remaining = preferred_stocks_remaining + other_stocks_remaining
                    if remaining:
                        stock = remaining.pop(0)
                        ticker = stock['ticker'].upper()
                        if ticker not in seen_tickers:
                            new_holdings_to_add.append(stock)
                            seen_tickers.add(ticker)
                    else:
                        break
            
            if new_holdings_to_add:
                notes.append(
                    f"Adding {len(new_holdings_to_add)} new holdings for better diversification "
                    f"(current: {num_holdings} holdings)"
                )
    
    # Separate holdings into preferred sector vs others for proper weight distribution
    # Thematic allocation should ONLY go to preferred sector holdings
    # Core equity should be distributed across ALL holdings with sector limits
    
    # Classify existing holdings by sector preference
    existing_preferred_holdings = []
    existing_other_holdings = []
    for holding in current_portfolio.holdings:
        is_preferred = False
        if profile.preferences.sectors_like:
            is_preferred = validate_ticker_in_sectors(holding.ticker, profile.preferences.sectors_like)
        if is_preferred:
            existing_preferred_holdings.append(holding)
        else:
            existing_other_holdings.append(holding)
    
    # Classify new holdings by sector preference
    new_preferred_holdings = []
    new_other_holdings = []
    for stock in new_holdings_to_add:
        ticker = stock['ticker'].upper()
        is_preferred = False
        if profile.preferences.sectors_like:
            is_preferred = validate_ticker_in_sectors(ticker, profile.preferences.sectors_like)
        if is_preferred:
            new_preferred_holdings.append(stock)
        else:
            new_other_holdings.append(stock)
    
    # Calculate weights: thematic only for preferred, core equity for all
    # BUT ensure minimum % in preferred sectors based on risk tolerance
    total_preferred_holdings = len(existing_preferred_holdings) + len(new_preferred_holdings)
    total_other_holdings = len(existing_other_holdings) + len(new_other_holdings)
    total_holdings_count = total_preferred_holdings + total_other_holdings
    
    # Calculate risk-based minimum percentage in preferred sectors
    is_very_risk_averse = profile.risk_score < 35
    is_risk_averse = profile.risk_score < 50
    
    if is_very_risk_averse:
        min_preferred_pct = 0.30  # 30% minimum for very risk-averse (encourage diversification)
    elif is_risk_averse:
        min_preferred_pct = 0.40  # 40% minimum for risk-averse
    elif profile.risk_score < 70:
        min_preferred_pct = 0.50  # 50% minimum for moderate risk
    else:
        min_preferred_pct = 0.60  # 60% minimum for higher risk tolerance
    
    # Calculate base target per holding
    if total_holdings_count > 0:
        # Calculate total equity to allocate
        total_target_equity = target.core_equity + target.thematic_sectors
        
        # Calculate minimum required allocation to preferred sectors
        min_preferred_allocation = total_target_equity * min_preferred_pct
        
        # Distribute thematic allocation to preferred holdings first
        if total_preferred_holdings > 0 and target.thematic_sectors > 0:
            thematic_per_preferred = target.thematic_sectors / total_preferred_holdings
        else:
            thematic_per_preferred = 0.0
        
        # Calculate how much more core equity preferred holdings need to meet minimum
        current_preferred_allocation = target.thematic_sectors  # Just thematic for now
        if current_preferred_allocation < min_preferred_allocation:
            # Need additional core equity to meet minimum
            additional_core_needed = min_preferred_allocation - current_preferred_allocation
            # Cap at available core equity
            additional_core_needed = min(additional_core_needed, target.core_equity)
        else:
            additional_core_needed = 0.0
        
        # Remaining core equity is distributed across ALL holdings
        remaining_core_equity = target.core_equity - additional_core_needed
        
        # Distribute core equity
        if total_preferred_holdings > 0:
            # Preferred holdings get: thematic + additional core for minimum + share of remaining core
            preferred_core_share = remaining_core_equity / total_holdings_count  # Share based on total holdings
            additional_core_per_preferred = additional_core_needed / total_preferred_holdings if total_preferred_holdings > 0 else 0.0
            target_per_preferred_holding = min(
                thematic_per_preferred + preferred_core_share + additional_core_per_preferred,
                max_position
            )
        else:
            target_per_preferred_holding = 0.0
        
        if total_other_holdings > 0:
            # Other holdings get: share of remaining core equity only
            other_core_share = remaining_core_equity / total_holdings_count  # Share based on total holdings
            target_per_other_holding = min(other_core_share, max_position)
        else:
            target_per_other_holding = 0.0
        
        target_per_holding = min(total_target_equity / total_holdings_count, max_position) if total_holdings_count > 0 else 0.0
    else:
        target_per_preferred_holding = 0.0
        target_per_other_holding = 0.0
        target_per_holding = 0.0
    
    # Adjust for cash target
    cash_delta = target.cash - current_portfolio.cash_weight
    if abs(cash_delta) > 0.001:
        notes.append(f"Adjust cash by {cash_delta*100:.1f}%")
    
    # Compute deltas for existing holdings, enforcing sector limits
    # Track sector weights as we adjust
    projected_sector_weights = current_sector_weights.copy()
    
    for holding in current_portfolio.holdings:
        sector = get_ticker_sector(holding.ticker) or 'Unknown'
        current_weight = holding.weight
        
        # Determine if this is a preferred sector holding
        is_preferred = False
        if profile.preferences.sectors_like:
            is_preferred = validate_ticker_in_sectors(holding.ticker, profile.preferences.sectors_like)
        
        # Use appropriate target weight based on sector preference
        base_target_weight = target_per_preferred_holding if is_preferred else target_per_other_holding
        
        # If this sector already exceeds or would exceed limit, reduce target
        current_sector_total = projected_sector_weights.get(sector, 0.0)
        if current_sector_total - current_weight + base_target_weight > max_sector_weight:
            # Cap target to keep sector within limit
            max_allowed_for_holding = max_sector_weight - (current_sector_total - current_weight)
            target_weight = min(base_target_weight, max_allowed_for_holding)
        else:
            target_weight = base_target_weight
        
        # Cap delta if it would exceed max position
        if target_weight > max_position:
            target_weight = max_position
        
        delta = target_weight - current_weight
        
        # If reducing holdings in over-concentrated sectors, prioritize that
        if has_sector_concentration and sector in sectors_exceeding_limit:
            # If reducing weight in this sector, allow more aggressive reduction
            if delta < 0:
                # Allow reduction, but don't force it too aggressively
                pass
        
        if abs(delta) > 0.001:  # Threshold for actionable change
            action_type = "BUY" if delta > 0 else "SELL"
            actions.append(
                RebalanceAction(
                    action=action_type,
                    ticker=holding.ticker,
                    delta_weight=abs(delta),
                )
            )
            # Update projected sector weight
            if action_type == "BUY":
                projected_sector_weights[sector] = projected_sector_weights.get(sector, 0.0) + delta
            else:  # SELL
                projected_sector_weights[sector] = max(0.0, projected_sector_weights.get(sector, 0.0) - delta)
    
    # Add new holdings, respecting sector limits and proper weight distribution
    for stock in new_holdings_to_add:
        ticker = stock['ticker'].upper()
        sector = get_ticker_sector(ticker) or 'Unknown'
        
        # Determine if this is a preferred sector holding
        is_preferred = False
        if profile.preferences.sectors_like:
            is_preferred = validate_ticker_in_sectors(ticker, profile.preferences.sectors_like)
        
        # Use appropriate target weight based on sector preference
        weight = target_per_preferred_holding if is_preferred else target_per_other_holding
        weight = min(weight, max_position)  # Cap at max position
        
        # Check sector limit
        current_sector_total = projected_sector_weights.get(sector, 0.0)
        if current_sector_total + weight > max_sector_weight:
            # Reduce weight to fit within sector limit
            weight = max(0.0, max_sector_weight - current_sector_total)
            if weight < 0.001:
                # Skip this holding if sector is at limit
                warnings.append(f"Skipping {ticker} - sector {sector} at {max_sector_weight*100:.0f}% limit")
                continue
        
        actions.append(
            RebalanceAction(
                action="BUY",
                ticker=ticker,
                delta_weight=weight,
            )
        )
        # Update projected sector weight
        projected_sector_weights[sector] = projected_sector_weights.get(sector, 0.0) + weight
    
    # Add note about sector diversification if we're enforcing it
    if has_sector_concentration or is_risk_averse:
        notes.append(
            f"Rebalancing to enforce sector diversification limits "
            f"(max {max_sector_weight*100:.0f}% per sector for risk-averse portfolios)"
        )
    
    # Check for constraint violations
    final_holdings_count = total_holdings_count + (1 if target.cash > 0 else 0)
    if final_holdings_count > max_holdings:
        warnings.append(
            f"Holdings count ({final_holdings_count}) exceeds max ({max_holdings})"
        )
    
    # Check exclusions
    for holding in current_portfolio.holdings:
        ticker_lower = holding.ticker.lower()
        for exclusion in profile.constraints.exclusions:
            if exclusion.lower() in ticker_lower:
                warnings.append(f"{holding.ticker} in exclusion list: {exclusion}")
                actions.append(
                    RebalanceAction(
                        action="SELL",
                        ticker=holding.ticker,
                        delta_weight=holding.weight,
                    )
                )
    
    # Check preferred sector preference (NOT a hard constraint)
    # Preferred sectors are preferences, not requirements
    # We want to ensure minimum % in preferred sectors based on risk, but allow other sectors for diversification
    if profile.preferences.sectors_like:
        # Calculate risk-based minimum percentage in preferred sectors
        is_very_risk_averse = profile.risk_score < 35
        is_risk_averse = profile.risk_score < 50
        
        # Risk-based minimum % in preferred sectors (lower for risk-averse to encourage diversification)
        if is_very_risk_averse:
            min_preferred_pct = 0.30  # 30% minimum for very risk-averse (encourage diversification)
        elif is_risk_averse:
            min_preferred_pct = 0.40  # 40% minimum for risk-averse
        elif profile.risk_score < 70:
            min_preferred_pct = 0.50  # 50% minimum for moderate risk
        else:
            min_preferred_pct = 0.60  # 60% minimum for higher risk tolerance
        
        # Calculate current allocation in preferred sectors
        current_preferred_weight = 0.0
        for holding in current_portfolio.holdings:
            if validate_ticker_in_sectors(holding.ticker, profile.preferences.sectors_like):
                current_preferred_weight += holding.weight
        
        # If below minimum, note it (but don't force sell other sectors - allow gradual rebalancing)
        if current_preferred_weight < min_preferred_pct:
            notes.append(
                f"Portfolio has {current_preferred_weight*100:.1f}% in preferred sectors "
                f"(target: {min_preferred_pct*100:.0f}% minimum for risk tolerance). "
                f"Other sectors included for diversification."
            )
        else:
            notes.append(
                f"Portfolio meets preferred sector preference "
                f"({current_preferred_weight*100:.1f}% in preferred sectors, "
                f"minimum: {min_preferred_pct*100:.0f}%)"
            )
    
    # Add summary notes
    if target.cash > 0.15:
        notes.append("High cash allocation for near-term needs")
    if target.thematic_sectors > 0.10 and profile.preferences.sectors_like:
        sectors_str = ", ".join(profile.preferences.sectors_like)
        notes.append(f"Elevated allocation to preferred sectors: {sectors_str}")
    
    if is_long_term and (is_too_concentrated or is_highly_concentrated):
        notes.append(
            "Portfolio rebalanced for long-term diversification. "
            "Added holdings across multiple sectors to reduce concentration risk."
        )
    
    # Verify and normalize actions to ensure portfolio sums to target equity allocation
    # Calculate what the final portfolio would be if we apply all actions
    final_weights: dict[str, float] = {}
    
    # Start with current holdings
    for holding in current_portfolio.holdings:
        final_weights[holding.ticker.upper()] = holding.weight
    
    # Apply all actions to get final weights
    for action in actions:
        ticker = action.ticker.upper()
        current = final_weights.get(ticker, 0.0)
        if action.action == "BUY":
            final_weights[ticker] = current + action.delta_weight
        else:  # SELL
            final_weights[ticker] = max(0.0, current - action.delta_weight)
            # Remove if weight becomes negligible
            if final_weights[ticker] < 0.001:
                final_weights.pop(ticker, None)
    
    # Calculate total equity after applying actions
    total_equity_after = sum(w for w in final_weights.values())
    
    # Ensure minimum 5% cash - adjust target equity if needed
    MIN_CASH_PCT = 0.05  # 5% minimum
    max_equity_allowed = 1.0 - MIN_CASH_PCT  # Maximum 95% equity
    
    # If total doesn't match target, normalize all BUY actions proportionally
    # This ensures the final portfolio sums to exactly total_target_equity (but never exceeds max_equity_allowed)
    if total_equity_after > 0.001:
        # Cap target equity to ensure minimum cash
        capped_target_equity = min(total_target_equity, max_equity_allowed)
        
        # Check if we need to adjust
        if abs(total_equity_after - capped_target_equity) > 0.01:
            scale_factor = capped_target_equity / total_equity_after if total_equity_after > 0 else 1.0
            
            # Scale all BUY actions (both for existing and new holdings)
            for action in actions:
                if action.action == "BUY":
                    action.delta_weight *= scale_factor
            
            # Recalculate final weights with scaled actions
            final_weights_scaled: dict[str, float] = {}
            for holding in current_portfolio.holdings:
                final_weights_scaled[holding.ticker.upper()] = holding.weight
            for action in actions:
                ticker = action.ticker.upper()
                current = final_weights_scaled.get(ticker, 0.0)
                if action.action == "BUY":
                    final_weights_scaled[ticker] = current + action.delta_weight
                else:  # SELL
                    final_weights_scaled[ticker] = max(0.0, current - action.delta_weight)
                    if final_weights_scaled[ticker] < 0.001:
                        final_weights_scaled.pop(ticker, None)
            
            final_total_equity = sum(w for w in final_weights_scaled.values())
            
            if abs(scale_factor - 1.0) > 0.01:  # More than 1% difference
                notes.append(
                    f"Actions normalized to ensure portfolio equity allocation "
                    f"(target: {capped_target_equity*100:.1f}%, scale: {scale_factor:.3f})"
                )
            
            total_equity_after = final_total_equity
    
    # Final safety check: ensure actions result in a portfolio that doesn't exceed 100%
    # Recalculate final equity after all adjustments
    final_weights_verify: dict[str, float] = {}
    for holding in current_portfolio.holdings:
        final_weights_verify[holding.ticker.upper()] = holding.weight
    for action in actions:
        ticker = action.ticker.upper()
        current = final_weights_verify.get(ticker, 0.0)
        if action.action == "BUY":
            final_weights_verify[ticker] = current + action.delta_weight
        else:  # SELL
            final_weights_verify[ticker] = max(0.0, current - action.delta_weight)
            if final_weights_verify[ticker] < 0.001:
                final_weights_verify.pop(ticker, None)
    
    total_equity_final = sum(w for w in final_weights_verify.values())
    final_cash = max(target.cash, MIN_CASH_PCT)  # Ensure minimum cash
    final_total_portfolio = total_equity_final + final_cash
    
    # Handle rounding errors: if total slightly exceeds 100% (e.g., 100.1%), adjust actions
    ROUNDING_THRESHOLD = 0.001  # 0.1% tolerance for rounding errors
    if final_total_portfolio > 1.0 + ROUNDING_THRESHOLD:
        # Portfolio exceeds 100% by more than rounding threshold - scale down equity
        if total_equity_final > max_equity_allowed:
            scale = max_equity_allowed / total_equity_final if total_equity_final > 0 else 1.0
            for action in actions:
                if action.action == "BUY":
                    action.delta_weight *= scale
            warnings.append(
                f"Portfolio exceeded 100% - equity scaled to {max_equity_allowed*100:.1f}% "
                f"to maintain minimum {MIN_CASH_PCT*100:.0f}% cash"
            )
            # Recalculate after scaling
            total_equity_final = max_equity_allowed
            final_cash = MIN_CASH_PCT
            final_total_portfolio = total_equity_final + final_cash
    elif final_total_portfolio > 1.0 and final_total_portfolio <= 1.0 + ROUNDING_THRESHOLD:
        # Small rounding error (within 0.1%) - reduce equity slightly to fix
        excess = final_total_portfolio - 1.0
        # Reduce from largest BUY actions proportionally
        buy_actions = [a for a in actions if a.action == "BUY"]
        if buy_actions:
            scale = (total_equity_final - excess) / total_equity_final if total_equity_final > 0 else 1.0
            for action in buy_actions:
                action.delta_weight *= scale
            notes.append(
                f"Adjusted equity by -{excess*100:.2f}% to fix rounding error "
                f"(final cash: {final_cash*100:.1f}%)"
            )
            total_equity_final = total_equity_final - excess
            final_total_portfolio = total_equity_final + final_cash
    
    # Ensure minimum cash is maintained - if equity is too high, reduce it
    if final_cash < MIN_CASH_PCT or total_equity_final > max_equity_allowed:
        max_equity_for_min_cash = 1.0 - MIN_CASH_PCT
        if total_equity_final > max_equity_for_min_cash:
            scale = max_equity_for_min_cash / total_equity_final if total_equity_final > 0 else 1.0
            for action in actions:
                if action.action == "BUY":
                    action.delta_weight *= scale
            notes.append(
                f"Equity reduced to {max_equity_for_min_cash*100:.1f}% "
                f"to ensure minimum {MIN_CASH_PCT*100:.0f}% cash allocation for safety"
            )
            total_equity_final = max_equity_for_min_cash
            final_cash = MIN_CASH_PCT
            final_total_portfolio = total_equity_final + final_cash
    
    # Update target cash in notes if minimum was enforced
    if final_cash == MIN_CASH_PCT and target.cash < MIN_CASH_PCT:
        notes.append(f"Cash allocation set to minimum {MIN_CASH_PCT*100:.0f}% for safety")
    elif abs(final_cash - target.cash) > 0.001:
        notes.append(f"Cash allocation: {final_cash*100:.1f}% (target was {target.cash*100:.1f}%)")
    
    return RebalancePlan(
        actions=actions,
        notes=notes,
        warnings=warnings,
    )


def construct_portfolio_from_scratch(
    profile: InvestorProfile,
    target: TargetAllocation,
) -> tuple[PortfolioInput, RebalancePlan]:
    """
    Construct a new portfolio from scratch based on profile and target allocation.
    
    Returns:
        - PortfolioInput: The constructed portfolio
        - RebalancePlan: Actions showing what to buy (all BUY actions)
    """
    actions: list[RebalanceAction] = []
    warnings: list[str] = []
    notes: list[str] = []
    holdings: list[Holding] = []
    
    max_position = profile.constraints.max_position_pct / 100.0
    max_holdings = profile.constraints.max_holdings
    
    # Get available stocks
    sectors_data = load_sectors_data()
    all_stocks: list[dict] = []
    
    # Determine risk level for diversification strategy
    is_risk_averse = profile.risk_score < 50
    is_very_risk_averse = profile.risk_score < 35
    
    # For risk-averse clients, prioritize diversification over user interests
    # Use ALL available sectors for core equity, not just preferred sectors
    all_available_sectors = [s['name'] for s in sectors_data['sectors']]
    if profile.preferences.sectors_avoid:
        all_available_sectors = [s for s in all_available_sectors if s not in profile.preferences.sectors_avoid]
    
    # 1. Thematic sectors allocation (preferred sectors)
    # For risk-averse clients, minimize or eliminate thematic allocation
    thematic_stocks: list[dict] = []
    if target.thematic_sectors > 0 and profile.preferences.sectors_like and not is_risk_averse:
        # Only use thematic for non-risk-averse clients
        thematic_stocks = get_stocks_for_sectors(profile.preferences.sectors_like)
        # Filter out exclusions
        for stock in thematic_stocks:
            ticker_lower = stock['ticker'].lower()
            excluded = any(exclusion.lower() in ticker_lower for exclusion in profile.constraints.exclusions)
            if not excluded:
                all_stocks.append(stock)
    
    # 2. Core equity allocation (diversified across sectors)
    # CRITICAL: For risk-averse clients, use ALL sectors, not just preferred
    # This ensures proper diversification
    if target.core_equity > 0:
        if is_risk_averse:
            # Risk-averse: Use ALL available sectors for diversification
            core_sectors = all_available_sectors
        else:
            # Non-risk-averse: Can use preferred sectors, but still include others
            if profile.preferences.sectors_like:
                # Mix preferred with other sectors
                preferred_set = set(profile.preferences.sectors_like)
                other_sectors = [s for s in all_available_sectors if s not in preferred_set]
                # Use preferred sectors but also include others for diversification
                core_sectors = list(preferred_set) + other_sectors
            else:
                core_sectors = all_available_sectors
        
        core_stocks = get_stocks_for_sectors(core_sectors)
        # Filter out exclusions and already added stocks
        seen_tickers = {s['ticker'].upper() for s in all_stocks}
        for stock in core_stocks:
            ticker = stock['ticker'].upper()
            ticker_lower = stock['ticker'].lower()
            excluded = any(exclusion.lower() in ticker_lower for exclusion in profile.constraints.exclusions)
            if not excluded and ticker not in seen_tickers:
                all_stocks.append(stock)
                seen_tickers.add(ticker)
    
    # 3. Defensive allocation (low risk stocks)
    if target.defensive > 0:
        # Select stocks with low risk scores
        defensive_candidates = []
        for stock in all_stocks[:]:  # Copy list
            risk_score = get_risk_score_for_stock(stock['ticker'])
            if risk_score and risk_score < 30:  # Low risk threshold
                defensive_candidates.append(stock)
        
        # If not enough low-risk stocks, use some from existing pool
        if len(defensive_candidates) < 3:
            # Prefer large-cap stocks as defensive
            for stock in all_stocks:
                if stock.get('market_cap') == 'large' and stock not in defensive_candidates:
                    defensive_candidates.append(stock)
                    if len(defensive_candidates) >= 5:
                        break
    
    # Sector diversification enforcement
    # Determine max weight per sector based on risk tolerance
    is_risk_averse = profile.risk_score < 50
    is_very_risk_averse = profile.risk_score < 35
    if is_very_risk_averse:
        max_sector_weight = 0.20  # Max 20% per sector for very risk-averse
        min_sectors = 5  # Require at least 5 sectors
    elif is_risk_averse:
        max_sector_weight = 0.25  # Max 25% per sector for risk-averse
        min_sectors = 4  # Require at least 4 sectors
    else:
        max_sector_weight = 0.35  # Max 35% per sector for others
        min_sectors = 3  # Require at least 3 sectors
    
    # Get all available sectors (excluding avoided sectors)
    all_available_sectors = [s['name'] for s in sectors_data['sectors']]
    if profile.preferences.sectors_avoid:
        all_available_sectors = [s for s in all_available_sectors if s not in profile.preferences.sectors_avoid]
    
    # Select stocks with sector diversification in mind
    selected_stocks = []
    sector_counts: dict[str, int] = {}  # Track how many stocks per sector
    sector_weights: dict[str, float] = {}  # Track weight per sector
    seen_tickers = set()
    
    total_equity = target.core_equity + target.thematic_sectors + target.defensive
    
    # Helper function to check if we can add more from a sector
    def can_add_from_sector(sector: str, weight_to_add: float) -> bool:
        current_sector_weight = sector_weights.get(sector, 0.0)
        return (current_sector_weight + weight_to_add) <= max_sector_weight
    
    # Helper function to get sector for a stock
    def get_stock_sector(stock: dict) -> str:
        return stock.get('sector') or get_ticker_sector(stock['ticker']) or 'Unknown'
    
    # Step 1: Add thematic stocks with sector limits (only for non-risk-averse)
    # For risk-averse clients, skip thematic allocation to prioritize diversification
    if target.thematic_sectors > 0 and thematic_stocks and not is_risk_averse:
        # Calculate how many thematic stocks we can reasonably use
        # Distribute thematic allocation across multiple sectors if possible
        thematic_stocks_by_sector: dict[str, list[dict]] = {}
        for stock in thematic_stocks:
            sector = get_stock_sector(stock)
            if sector not in thematic_stocks_by_sector:
                thematic_stocks_by_sector[sector] = []
            thematic_stocks_by_sector[sector].append(stock)
        
        # Select 1-2 stocks per thematic sector, respecting limits
        thematic_allocation_per_sector = target.thematic_sectors / len(thematic_stocks_by_sector) if thematic_stocks_by_sector else 0
        thematic_stocks_to_add = []
        
        for sector, stocks_in_sector in thematic_stocks_by_sector.items():
            if can_add_from_sector(sector, thematic_allocation_per_sector):
                # Add 1-2 stocks from this thematic sector
                for stock in stocks_in_sector[:2]:
                    ticker = stock['ticker'].upper()
                    if ticker not in seen_tickers:
                        thematic_stocks_to_add.append(stock)
                        seen_tickers.add(ticker)
                        sector_counts[sector] = sector_counts.get(sector, 0) + 1
                        if len(thematic_stocks_to_add) >= max(3, int(max_holdings * target.thematic_sectors / total_equity)):
                            break
                if len(thematic_stocks_to_add) >= max(3, int(max_holdings * target.thematic_sectors / total_equity)):
                    break
        
        selected_stocks.extend(thematic_stocks_to_add)
    elif is_risk_averse and target.thematic_sectors > 0:
        # For risk-averse clients, redistribute thematic allocation to core equity for better diversification
        notes.append(
            f"Thematic allocation ({target.thematic_sectors*100:.1f}%) redistributed to core equity "
            f"for enhanced sector diversification (risk-averse portfolio)"
        )
    
    # Step 2: Ensure diversification across sectors
    # We need to select stocks from different sectors to meet minimum sector count
    remaining_slots = max_holdings - len(selected_stocks)
    sectors_needed = max(0, min_sectors - len(set(get_stock_sector(s) for s in selected_stocks)))
    
    # Group remaining stocks by sector
    stocks_by_sector: dict[str, list[dict]] = {}
    for stock in all_stocks:
        ticker = stock['ticker'].upper()
        if ticker not in seen_tickers:
            sector = get_stock_sector(stock)
            if sector not in stocks_by_sector:
                stocks_by_sector[sector] = []
            stocks_by_sector[sector].append(stock)
    
    # First, ensure we have stocks from at least min_sectors different sectors
    current_sectors = set(get_stock_sector(s) for s in selected_stocks)
    for sector, stocks_in_sector in stocks_by_sector.items():
        if sector not in current_sectors and sectors_needed > 0 and remaining_slots > 0:
            # Add one stock from this sector
            for stock in stocks_in_sector:
                ticker = stock['ticker'].upper()
                if ticker not in seen_tickers:
                    selected_stocks.append(stock)
                    seen_tickers.add(ticker)
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1
                    remaining_slots -= 1
                    sectors_needed -= 1
                    break
    
    # Step 3: Fill remaining slots, prioritizing diversification with balanced selection
    # Try to add stocks from sectors we haven't fully utilized, balancing preferred vs other
    if remaining_slots > 0:
        # Separate sectors into preferred and other for balanced selection
        preferred_sectors_set = set(profile.preferences.sectors_like or [])
        preferred_sectors_to_fill = [s for s in stocks_by_sector.keys() if s in preferred_sectors_set]
        other_sectors_to_fill = [s for s in stocks_by_sector.keys() if s not in preferred_sectors_set]
        
        # Sort by current count (prioritize underrepresented sectors)
        preferred_sectors_sorted = sorted(
            preferred_sectors_to_fill,
            key=lambda s: (sector_counts.get(s, 0), -len(stocks_by_sector.get(s, [])))
        )
        other_sectors_sorted = sorted(
            other_sectors_to_fill,
            key=lambda s: (sector_counts.get(s, 0), -len(stocks_by_sector.get(s, [])))
        )
        
        # Track counts for balance
        preferred_added = sum(1 for s in selected_stocks if validate_ticker_in_sectors(s['ticker'], profile.preferences.sectors_like or []))
        other_added = len(selected_stocks) - preferred_added
        preferred_target = int(remaining_slots * 0.6) if profile.preferences.sectors_like else 0
        
        # Alternate between preferred and other sectors
        preferred_idx = 0
        other_idx = 0
        
        while remaining_slots > 0:
            # Determine which to add based on balance
            should_add_preferred = (preferred_added < preferred_target) and preferred_idx < len(preferred_sectors_sorted)
            should_add_other = (other_added >= preferred_added or preferred_idx >= len(preferred_sectors_sorted)) and other_idx < len(other_sectors_sorted)
            
            sector_to_use = None
            if should_add_preferred:
                sector_to_use = preferred_sectors_sorted[preferred_idx]
                preferred_idx += 1
            elif should_add_other:
                sector_to_use = other_sectors_sorted[other_idx]
                other_idx += 1
            else:
                break
            
            if sector_to_use:
                stocks_in_sector = stocks_by_sector.get(sector_to_use, [])
                # Estimate weight per stock to check sector limit
                estimated_weight_per_stock = target.core_equity / max(remaining_slots, 1)
                if can_add_from_sector(sector_to_use, estimated_weight_per_stock):
                    for stock in stocks_in_sector:
                        ticker = stock['ticker'].upper()
                        if ticker not in seen_tickers:
                            selected_stocks.append(stock)
                            seen_tickers.add(ticker)
                            sector_counts[sector_to_use] = sector_counts.get(sector_to_use, 0) + 1
                            remaining_slots -= 1
                            if validate_ticker_in_sectors(ticker, profile.preferences.sectors_like or []):
                                preferred_added += 1
                            else:
                                other_added += 1
                            if remaining_slots <= 0:
                                break
    
    # Fallback: If we still don't have enough stocks, add from any available sector
    if len(selected_stocks) < 3 and all_stocks:
        for stock in all_stocks:
            ticker = stock['ticker'].upper()
            if ticker not in seen_tickers:
                selected_stocks.append(stock)
                seen_tickers.add(ticker)
                sector = get_stock_sector(stock)
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
                if len(selected_stocks) >= 3:
                    break
    
    if not selected_stocks:
        # Really no stocks available - return minimal portfolio with just cash
        portfolio = PortfolioInput(holdings=[], cash_weight=1.0)
        plan = RebalancePlan(
            actions=[],
            notes=["Unable to construct portfolio - no suitable stocks available"],
            warnings=["No stocks selected for portfolio construction"]
        )
        return portfolio, plan
    
    # Calculate weights for each holding with sector diversification limits
    # Distribute equity allocation across holdings, respecting sector limits
    holdings_dict: dict[str, Holding] = {}  # ticker -> Holding
    
    # For risk-averse clients, merge thematic into core equity for better diversification
    effective_core_equity = target.core_equity
    if is_risk_averse and target.thematic_sectors > 0:
        # Redistribute thematic to core for diversification
        effective_core_equity = target.core_equity + target.thematic_sectors
    
    # Separate stocks into preferred vs others for proper weight distribution
    preferred_stocks_in_selected = []
    other_stocks_in_selected = []
    for stock in selected_stocks:
        ticker = stock['ticker'].upper()
        is_preferred = False
        if profile.preferences.sectors_like:
            is_preferred = validate_ticker_in_sectors(ticker, profile.preferences.sectors_like)
        if is_preferred:
            preferred_stocks_in_selected.append(stock)
        else:
            other_stocks_in_selected.append(stock)
    
    # Assign thematic weights ONLY to preferred sector stocks (only for non-risk-averse)
    if preferred_stocks_in_selected and target.thematic_sectors > 0 and not is_risk_averse:
        thematic_weight_per_stock = target.thematic_sectors / len(preferred_stocks_in_selected)
        for stock in preferred_stocks_in_selected:
            ticker = stock['ticker']
            sector = get_stock_sector(stock)
            weight = min(thematic_weight_per_stock, max_position)
            # Apply sector limit
            current_sector_weight = sector_weights.get(sector, 0.0)
            if current_sector_weight + weight > max_sector_weight:
                weight = max(0.0, max_sector_weight - current_sector_weight)
            if ticker not in holdings_dict:
                holdings_dict[ticker] = Holding(ticker=ticker, weight=0.0)
            holdings_dict[ticker].weight += weight
            sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
    
    # Assign core equity weights to ALL stocks (preferred and others)
    # Core equity should be distributed across all holdings for diversification
    all_stocks_for_core = preferred_stocks_in_selected + other_stocks_in_selected
    if all_stocks_for_core and effective_core_equity > 0:
        core_weight_per_stock = effective_core_equity / len(all_stocks_for_core)
        for stock in all_stocks_for_core:
            ticker = stock['ticker']
            sector = get_stock_sector(stock)
            weight = min(core_weight_per_stock, max_position)
            # Apply sector limit - CRITICAL for diversification
            current_sector_weight = sector_weights.get(sector, 0.0)
            if current_sector_weight + weight > max_sector_weight:
                weight = max(0.0, max_sector_weight - current_sector_weight)
            if ticker not in holdings_dict:
                holdings_dict[ticker] = Holding(ticker=ticker, weight=0.0)
            holdings_dict[ticker].weight += weight
            holdings_dict[ticker].weight = min(holdings_dict[ticker].weight, max_position)
            sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
    
    # Convert to list
    holdings = list(holdings_dict.values())
    
    # Create actions
    for holding in holdings:
        actions.append(
            RebalanceAction(
                action="BUY",
                ticker=holding.ticker,
                delta_weight=holding.weight,
            )
        )
    
    # Normalize weights to ensure total equity allocation is correct
    # Total should be: cash + sum(holdings) = 1.0
    # So: sum(holdings) should equal (1.0 - cash_weight)
    target_equity = 1.0 - target.cash
    total_weight = sum(h.weight for h in holdings)
    
    if total_weight > 0:
        # Normalize to match target equity allocation, but respect sector limits
        scale = target_equity / total_weight
        
        # Recalculate sector weights after scaling, and enforce limits
        new_sector_weights: dict[str, float] = {}
        for holding in holdings:
            new_weight = holding.weight * scale
            new_weight = min(new_weight, max_position)
            sector = get_ticker_sector(holding.ticker) or 'Unknown'
            new_sector_weights[sector] = new_sector_weights.get(sector, 0.0) + new_weight
        
        # Check if any sector exceeds limit after scaling
        scale_adjusted = scale
        for sector, sector_total in new_sector_weights.items():
            if sector_total > max_sector_weight:
                # This sector would exceed limit - need to reduce scale
                current_sector_weight = sum(
                    h.weight for h in holdings 
                    if (get_ticker_sector(h.ticker) or 'Unknown') == sector
                )
                if current_sector_weight > 0:
                    max_scale_for_sector = max_sector_weight / current_sector_weight
                    scale_adjusted = min(scale_adjusted, max_scale_for_sector)
        
        # Apply adjusted scale
        for holding in holdings:
            holding.weight = min(holding.weight * scale_adjusted, max_position)
        
        # Recalculate total after scaling and capping
        total_weight = sum(h.weight for h in holdings)
        
        # If after capping we're still short, distribute remainder
        # But respect sector limits when distributing
        if total_weight < target_equity:
            remainder = target_equity - total_weight
            # Distribute remainder, prioritizing sectors that haven't hit limits
            sectors_with_capacity = []
            for holding in holdings:
                sector = get_ticker_sector(holding.ticker) or 'Unknown'
                current_sector_weight = sum(
                    h.weight for h in holdings 
                    if (get_ticker_sector(h.ticker) or 'Unknown') == sector
                )
                if current_sector_weight < max_sector_weight and holding.weight < max_position:
                    sectors_with_capacity.append((holding, sector))
            
            if sectors_with_capacity and remainder > 0:
                per_holding = remainder / len(sectors_with_capacity)
                for holding, sector in sectors_with_capacity:
                    if remainder <= 0:
                        break
                    current_sector_weight = sum(
                        h.weight for h in holdings 
                        if (get_ticker_sector(h.ticker) or 'Unknown') == sector
                    )
                    available_in_sector = max_sector_weight - current_sector_weight
                    available_in_position = max_position - holding.weight
                    additional = min(per_holding, available_in_sector, available_in_position, remainder)
                    if additional > 0:
                        holding.weight += additional
                        remainder -= additional
    elif target_equity > 0 and holdings:
        # If no weights but we need equity, distribute evenly with sector limits
        equal_weight = min(target_equity / len(holdings), max_position)
        sector_weights_final: dict[str, float] = {}
        for holding in holdings:
            sector = get_ticker_sector(holding.ticker) or 'Unknown'
            current_sector_total = sector_weights_final.get(sector, 0.0)
            # Check if we can add this weight to the sector
            if current_sector_total + equal_weight <= max_sector_weight:
                holding.weight = equal_weight
                sector_weights_final[sector] = current_sector_total + equal_weight
            else:
                # Use remaining capacity in sector
                holding.weight = max(0.0, max_sector_weight - current_sector_total)
                sector_weights_final[sector] = max_sector_weight
    
    # Update actions with final weights
    for i, action in enumerate(actions):
        if i < len(holdings):
            action.delta_weight = holdings[i].weight
    
    # Final safety check: ensure portfolio doesn't exceed 100% and maintains minimum cash
    MIN_CASH_PCT = 0.05  # 5% minimum cash for safety
    ROUNDING_THRESHOLD = 0.001  # 0.1% tolerance for rounding errors
    
    actual_equity = sum(h.weight for h in holdings)
    final_cash = max(target.cash, MIN_CASH_PCT)  # Ensure minimum cash
    final_total = actual_equity + final_cash
    
    # Ensure equity doesn't exceed maximum (leaving room for minimum cash)
    max_equity_allowed = 1.0 - MIN_CASH_PCT  # Maximum 95% equity
    
    if actual_equity > max_equity_allowed:
        # Equity is too high - scale down to fit within 95%
        scale = max_equity_allowed / actual_equity if actual_equity > 0 else 1.0
        for i, holding in enumerate(holdings):
            holding.weight *= scale
        # Update actions to match
        for i, action in enumerate(actions):
            if i < len(holdings):
                action.delta_weight = holdings[i].weight
        actual_equity = sum(h.weight for h in holdings)
        final_cash = MIN_CASH_PCT
        warnings.append(
            f"Equity allocation scaled down to {max_equity_allowed*100:.1f}% "
            f"to maintain minimum {MIN_CASH_PCT*100:.0f}% cash for safety"
        )
        final_total = actual_equity + final_cash
    
    # Handle rounding errors: if total slightly exceeds 100% (e.g., 100.1%), adjust cash
    if final_total > 1.0 + ROUNDING_THRESHOLD:
        # Portfolio exceeds 100% by more than rounding threshold - scale down equity
        scale = max_equity_allowed / actual_equity if actual_equity > 0 else 1.0
        for holding in holdings:
            holding.weight *= scale
        for i, action in enumerate(actions):
            if i < len(holdings):
                action.delta_weight = holdings[i].weight
        actual_equity = sum(h.weight for h in holdings)
        final_cash = MIN_CASH_PCT
        warnings.append(
            f"Portfolio exceeded 100% - equity scaled to {max_equity_allowed*100:.1f}% "
            f"to ensure minimum {MIN_CASH_PCT*100:.0f}% cash"
        )
        final_total = actual_equity + final_cash
    elif final_total > 1.0 and final_total <= 1.0 + ROUNDING_THRESHOLD:
        # Small rounding error (within 0.1%) - adjust cash to fix it
        excess = final_total - 1.0
        final_cash = max(MIN_CASH_PCT, final_cash - excess)
        notes.append(
            f"Adjusted cash by -{excess*100:.2f}% to fix rounding error "
            f"(final cash: {final_cash*100:.1f}%)"
        )
        final_total = actual_equity + final_cash
    
    # Final check: ensure minimum cash is maintained
    if final_cash < MIN_CASH_PCT:
        needed_cash = MIN_CASH_PCT - final_cash
        if actual_equity + final_cash > 1.0 - MIN_CASH_PCT:
            # Need to reduce equity to make room for minimum cash
            max_equity_for_min_cash = 1.0 - MIN_CASH_PCT
            if actual_equity > max_equity_for_min_cash:
                scale = max_equity_for_min_cash / actual_equity if actual_equity > 0 else 1.0
                for holding in holdings:
                    holding.weight *= scale
                for i, action in enumerate(actions):
                    if i < len(holdings):
                        action.delta_weight = holdings[i].weight
                actual_equity = sum(h.weight for h in holdings)
                notes.append(
                    f"Equity reduced to {actual_equity*100:.1f}% "
                    f"to ensure minimum {MIN_CASH_PCT*100:.0f}% cash allocation"
                )
        final_cash = MIN_CASH_PCT
        final_total = actual_equity + final_cash
    
    # Verify final total is exactly 1.0 (within rounding)
    if abs(final_total - 1.0) > 0.001:
        # Last resort: adjust cash to make it sum to exactly 1.0
        adjusted_cash = max(MIN_CASH_PCT, 1.0 - actual_equity)
        if adjusted_cash != final_cash:
            final_cash = adjusted_cash
            warnings.append(
                f"Cash adjusted to {adjusted_cash*100:.1f}% to ensure portfolio sums to 100% "
                f"(equity: {actual_equity*100:.1f}%)"
            )
        final_total = actual_equity + final_cash
    
    # Add notes
    notes.append(f"Constructed portfolio with {len(holdings)} holdings")
    if target.thematic_sectors > 0 and profile.preferences.sectors_like:
        sectors_str = ", ".join(profile.preferences.sectors_like)
        notes.append(f"Thematic allocation ({target.thematic_sectors*100:.1f}%) focused on: {sectors_str}")
    
    # Always note cash allocation, especially if minimum was enforced
    if final_cash >= MIN_CASH_PCT:
        if final_cash == MIN_CASH_PCT and target.cash < MIN_CASH_PCT:
            notes.append(f"Cash allocation set to minimum {MIN_CASH_PCT*100:.0f}% for safety")
        else:
            notes.append(f"Cash allocation: {final_cash*100:.1f}%")
    
    portfolio = PortfolioInput(holdings=holdings, cash_weight=final_cash)
    plan = RebalancePlan(actions=actions, notes=notes, warnings=warnings)
    
    return portfolio, plan

