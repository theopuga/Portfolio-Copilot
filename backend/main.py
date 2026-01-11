"""FastAPI main application."""

import os
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .models import (
    ProfileInitRequest,
    ProfileUpdateRequest,
    AnalyzeRequest,
    RecommendRequest,
    RecommendationResponse,
    InvestorProfile,
    PortfolioMetrics,
    PortfolioInput,
    ErrorResponse,
    TickerLookupResult,
    PortfolioSnapshotRequest,
    PortfolioSnapshot,
    PortfolioHistoryResponse,
    CompareRequest,
    PortfolioComparison,
)
from .backboard_client import BackboardClient
from .portfolio import compute_metrics, compute_target_allocation, compute_rebalance_plan
from .sector_data import get_ticker_sector
from .logging_config import setup_logging

# Setup logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE")
setup_logging(log_level=LOG_LEVEL, log_file=LOG_FILE)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Portfolio Copilot API",
    description="Stateful Investment Portfolio Copilot powered by Backboard.io",
    version="1.0.0",
)

# CORS configuration - allow all for localhost deployment
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
# Note: * is fine for localhost-only deployment

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    start_time = datetime.utcnow()
    logger.info(f"{request.method} {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")
    
    try:
        response = await call_next(request)
        process_time = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.3f}s")
        return response
    except Exception as e:
        logger.error(f"Error processing {request.method} {request.url.path}: {e}", exc_info=True)
        raise

# Exception handler for Pydantic validation errors
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    errors = exc.errors()
    error_messages = [f"{err['loc']}: {err['msg']}" for err in errors]
    error_detail = "; ".join(error_messages)
    
    error_response = ErrorResponse(
        error="Validation error",
        error_code="VALIDATION_ERROR",
        detail=error_detail,
    )
    return JSONResponse(
        status_code=422,
        content=error_response.model_dump()
    )

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    error_response = ErrorResponse(
        error="Internal server error",
        error_code="INTERNAL_ERROR",
        detail="An unexpected error occurred. Please contact support if this persists.",
    )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump()
    )

# Initialize Backboard client
backboard = BackboardClient()
logger.info("Application initialized")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Portfolio Copilot API",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "POST /profile/init": "Initialize investor profile",
            "POST /profile/update": "Update investor profile",
            "POST /portfolio/analyze": "Analyze portfolio metrics",
            "POST /recommend": "Get rebalance recommendation",
            "GET /health": "Health check",
            "GET /profile/{user_id}": "Get investor profile",
            "POST /portfolio/snapshot": "Save portfolio snapshot",
            "GET /portfolio/history/{user_id}": "Get portfolio history",
            "POST /portfolio/compare": "Compare two portfolios",
        },
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Quick check if Backboard client is initialized
        is_backboard_connected = backboard._sdk_client is not None
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "backboard_connected": is_backboard_connected,
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@app.post("/profile/init", response_model=InvestorProfile)
async def init_profile(request: ProfileInitRequest):
    """
    Initialize investor profile from onboarding text.
    
    Uses Backboard CHEAP model to extract structured profile.
    """
    try:
        # Log received text length to verify it's not truncated
        logger.info(f"Received profile init request - onboarding_text length: {len(request.onboarding_text)}")
        if len(request.onboarding_text) > 1000:
            logger.info(f"First 500 chars: {request.onboarding_text[:500]}...")
            logger.info(f"Last 500 chars: ...{request.onboarding_text[-500:]}")
        
        # Extract profile using CHEAP model
        profile = await backboard.cheap_extract_profile(request.onboarding_text)
        profile.user_id = request.user_id
        profile.last_updated = datetime.utcnow().isoformat()
        
        # Store in Backboard memory (this also stores in in-memory cache)
        success = await backboard.set_profile(request.user_id, profile)
        if not success:
            logger.error(f"Failed to store profile for user: {request.user_id}")
        
        # Verify profile is accessible immediately after storing
        verify_profile = await backboard.get_profile(request.user_id)
        if not verify_profile:
            logger.error(f"CRITICAL: Profile was stored but cannot be retrieved for user: {request.user_id}")
            error_response = ErrorResponse(
                error="Profile storage verification failed",
                error_code="PROFILE_STORAGE_ERROR",
                detail=f"Profile was created but could not be verified. Please try again.",
            )
            return JSONResponse(
                status_code=500,
                content=error_response.model_dump()
            )
        
        # Log decision
        await backboard.append_decision(
            request.user_id,
            f"Profile initialized: {profile.objective.type}, risk={profile.risk_score}, horizon={profile.horizon_months}mo",
        )
        
        logger.info(f"Profile initialized and verified for user: {request.user_id}")
        return profile
    except Exception as e:
        logger.error(f"Error initializing profile for user {request.user_id}: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error initializing profile",
            error_code="PROFILE_INIT_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/profile/update", response_model=InvestorProfile)
async def update_profile(request: ProfileUpdateRequest):
    """
    Update investor profile from update text.
    
    Uses Backboard CHEAP model to patch existing profile.
    """
    try:
        # Log received text length to verify it's not truncated
        logger.info(f"Received profile update request - update_text length: {len(request.update_text)}")
        if len(request.update_text) > 1000:
            logger.info(f"First 500 chars: {request.update_text[:500]}...")
            logger.info(f"Last 500 chars: ...{request.update_text[-500:]}")
        
        # Get current profile
        current_profile = await backboard.get_profile(request.user_id)
        if not current_profile:
            error_response = ErrorResponse(
                error="Profile not found",
                error_code="PROFILE_NOT_FOUND",
                detail=f"Profile not found for user_id: {request.user_id}",
            )
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump()
            )
        
        # Update using CHEAP model
        updated_profile = await backboard.cheap_update_profile(
            current_profile, request.update_text
        )
        updated_profile.user_id = request.user_id
        updated_profile.last_updated = datetime.utcnow().isoformat()
        
        # Store updated profile
        await backboard.set_profile(request.user_id, updated_profile)
        
        # Log decision
        await backboard.append_decision(
            request.user_id,
            f"Profile updated: {request.update_text[:100]}",
        )
        
        logger.info(f"Profile updated for user: {request.user_id}")
        return updated_profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile for user {request.user_id}: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error updating profile",
            error_code="PROFILE_UPDATE_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/portfolio/analyze", response_model=PortfolioMetrics)
async def analyze_portfolio(request: AnalyzeRequest):
    """
    Analyze portfolio and compute metrics.
    
    All computation is done locally (no LLM calls).
    Automatically looks up unknown tickers and adds them to database.
    """
    try:
        # Check for unknown tickers and look them up
        from .ticker_lookup import ticker_exists, lookup_or_add_ticker
        
        unknown_tickers = []
        lookup_results = []
        
        for holding in request.holdings:
            if not ticker_exists(holding.ticker):
                unknown_tickers.append(holding.ticker)
        
        # Look up unknown tickers (parallelize for performance)
        import asyncio
        lookup_tasks = [lookup_or_add_ticker(ticker) for ticker in unknown_tickers]
        lookup_results_raw = await asyncio.gather(*lookup_tasks, return_exceptions=True)
        
        # Process lookup results
        for i, result in enumerate(lookup_results_raw):
            ticker = unknown_tickers[i]
            if isinstance(result, Exception):
                lookup_results.append(TickerLookupResult(
                    ticker=ticker.upper(),
                    success=False,
                    message=f"Error during lookup: {str(result)}"
                ))
                logger.warning(f"Failed to lookup ticker {ticker}: {result}")
            else:
                success, message = result
                lookup_results.append(TickerLookupResult(
                    ticker=ticker.upper(),
                    success=success,
                    message=message
                ))
                if not success:
                    logger.warning(f"Failed to lookup ticker {ticker}: {message}")
        
        # Get profile for constraint checking
        profile = await backboard.get_profile(request.user_id)
        
        # Build portfolio input
        portfolio = PortfolioInput(
            holdings=request.holdings,
            cash_weight=request.cash_weight,
        )
        
        # Compute metrics
        metrics = compute_metrics(portfolio, profile)
        
        # Add lookup results to metrics
        metrics.ticker_lookups = lookup_results
        
        return metrics
    except ValueError as e:
        error_response = ErrorResponse(
            error="Validation error",
            error_code="VALIDATION_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=400,
            content=error_response.model_dump()
        )
    except Exception as e:
        logger.error(f"Error analyzing portfolio: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error analyzing portfolio",
            error_code="ANALYSIS_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/recommend", response_model=RecommendationResponse)
async def recommend_rebalance(request: RecommendRequest):
    """
    Get portfolio recommendation.
    
    Two modes:
    1. If holdings is empty: Construct a new portfolio from scratch
    2. If holdings provided: Rebalance existing portfolio
    
    Combines:
    - Stored profile from Backboard memory
    - Local portfolio metrics computation
    - Local portfolio construction OR rebalance plan computation
    - STRONG model explanation (unless budget mode)
    """
    try:
        # Get profile from Backboard memory
        profile = await backboard.get_profile(request.user_id)
        if not profile:
            error_response = ErrorResponse(
                error="Profile not found",
                error_code="PROFILE_NOT_FOUND",
                detail=f"Profile not found for user_id: {request.user_id}. Please initialize profile first.",
            )
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump()
            )
        
        # Compute target allocation
        target = compute_target_allocation(profile)
        
        # Determine if constructing new portfolio or rebalancing existing
        is_new_portfolio = not request.holdings or len(request.holdings) == 0
        
        if is_new_portfolio:
            # Construct portfolio from scratch
            from .portfolio import construct_portfolio_from_scratch
            portfolio, plan = construct_portfolio_from_scratch(profile, target)
            logger.info(f"Constructed new portfolio with {len(portfolio.holdings)} holdings for user {request.user_id}")
        else:
            # Check for unknown tickers and look them up before rebalancing
            from .ticker_lookup import ticker_exists, lookup_or_add_ticker
            
            unknown_tickers = []
            for holding in request.holdings:
                if not ticker_exists(holding.ticker):
                    unknown_tickers.append(holding.ticker)
            
            # Look up unknown tickers (parallelize for performance)
            import asyncio
            lookup_tasks = [lookup_or_add_ticker(ticker) for ticker in unknown_tickers]
            lookup_results_raw = await asyncio.gather(*lookup_tasks, return_exceptions=True)
            
            # Process lookup results
            lookup_results = []
            for i, result in enumerate(lookup_results_raw):
                ticker = unknown_tickers[i]
                if isinstance(result, Exception):
                    lookup_results.append({
                        "ticker": ticker.upper(),
                        "success": False,
                        "message": f"Error during lookup: {str(result)}"
                    })
                    logger.warning(f"Failed to lookup ticker {ticker}: {result}")
                else:
                    success, message = result
                    lookup_results.append({
                        "ticker": ticker.upper(),
                        "success": success,
                        "message": message
                    })
                    if not success:
                        logger.warning(f"Failed to lookup ticker {ticker}: {message}")
            
            # Build portfolio input from existing holdings
            portfolio = PortfolioInput(
                holdings=request.holdings,
                cash_weight=request.cash_weight,
            )
            
            # Compute rebalance plan
            plan = compute_rebalance_plan(portfolio, profile, target)
            logger.info(f"Computed rebalance plan with {len(plan.actions)} actions for user {request.user_id}")
        
        # Compute metrics locally
        metrics = compute_metrics(portfolio, profile)
        
        # Prepare enhanced context for AI explanation
        plan_dict = plan.model_dump()
        plan_dict['_is_new_portfolio'] = is_new_portfolio
        
        # Build detailed portfolio context for better AI recommendations
        current_portfolio_context = {}
        if portfolio.holdings:
            if is_new_portfolio:
                # For new portfolios, show what was constructed
                current_portfolio_context['constructed_portfolio'] = [
                    {
                        'ticker': h.ticker,
                        'weight_pct': round(h.weight * 100, 2),
                        'sector': get_ticker_sector(h.ticker) or 'Unknown'
                    }
                    for h in sorted(portfolio.holdings, key=lambda x: x.weight, reverse=True)
                ]
                current_portfolio_context['total_holdings_constructed'] = len(portfolio.holdings)
            else:
                # For rebalances, show current state before changes
                current_portfolio_context['current_holdings'] = [
                    {
                        'ticker': h.ticker,
                        'weight_pct': round(h.weight * 100, 2),
                        'sector': get_ticker_sector(h.ticker) or 'Unknown'
                    }
                    for h in sorted(portfolio.holdings, key=lambda x: x.weight, reverse=True)
                ]
                current_portfolio_context['current_cash_pct'] = round(portfolio.cash_weight * 100, 2)
            
            # Always include sector allocation and concentration metrics
            current_portfolio_context['sector_allocation'] = {
                sector: round(weight * 100, 2)
                for sector, weight in metrics.sector_allocation.items()
            }
            current_portfolio_context['concentration_analysis'] = {
                'top_1_pct': round(metrics.top_1_weight * 100, 2),
                'top_3_pct': round(metrics.top_3_weight * 100, 2),
                'top_5_pct': round(metrics.top_5_weight * 100, 2),
                'hhi': round(metrics.herfindahl_index, 3),
                'total_holdings': metrics.total_holdings
            }
            if not is_new_portfolio:
                current_portfolio_context['current_sector_allocation'] = current_portfolio_context['sector_allocation']
        
        # Target allocation context - ensure minimum 5% cash for safety
        MIN_CASH_PCT = 0.05
        target_cash = max(target.cash, MIN_CASH_PCT)  # Ensure minimum cash
        
        # Determine sector diversification limits based on risk tolerance
        is_risk_averse = profile.risk_score < 50
        is_very_risk_averse = profile.risk_score < 35
        if is_very_risk_averse:
            max_sector_weight_pct = 20.0
        elif is_risk_averse:
            max_sector_weight_pct = 25.0
        else:
            max_sector_weight_pct = 35.0
        
        target_context = {
            'target_allocation': {
                'cash_pct': round(target_cash * 100, 2),
                'core_equity_pct': round(target.core_equity * 100, 2),
                'thematic_sectors_pct': round(target.thematic_sectors * 100, 2),
                'defensive_pct': round(target.defensive * 100, 2),
                'final_cash_pct': round(target_cash * 100, 2)  # Final cash after applying actions
            },
            'profile_key_factors': {
                'risk_score': profile.risk_score,
                'horizon_months': profile.horizon_months,
                'objective': profile.objective.type,
                'preferred_sectors': profile.preferences.sectors_like or [],
                'excluded_sectors': profile.preferences.sectors_avoid or [],
                'max_holdings': profile.constraints.max_holdings,
                'max_position_pct': profile.constraints.max_position_pct,
                'exclusions': profile.constraints.exclusions or [],
                'is_risk_averse': is_risk_averse,
                'is_very_risk_averse': is_very_risk_averse,
                'max_sector_weight_pct': max_sector_weight_pct,
                'diversification_note': f"Sector diversification limits: max {max_sector_weight_pct}% per sector {'(enhanced for risk-averse portfolio)' if is_risk_averse else ''}"
            }
        }
        
        # Add target cash to plan notes if it was adjusted to minimum
        if target_cash > target.cash and abs(target_cash - MIN_CASH_PCT) < 0.001:
            plan.notes.append(f"Target cash allocation set to minimum {MIN_CASH_PCT*100:.0f}% for safety")
        
        # Enhanced metrics with recommendations context
        enhanced_metrics = metrics.model_dump()
        enhanced_metrics['current_portfolio_context'] = current_portfolio_context
        enhanced_metrics['target_context'] = target_context
        
        explanation = await backboard.strong_generate_explanation(
            profile,
            enhanced_metrics,
            plan_dict,
        )
        
        return RecommendationResponse(
            profile=profile,
            metrics=metrics,
            plan=plan,
            explanation=explanation,
            operation_type="construct" if is_new_portfolio else "rebalance",
        )
    except HTTPException:
        raise
    except ValueError as e:
        error_response = ErrorResponse(
            error="Validation error",
            error_code="VALIDATION_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=400,
            content=error_response.model_dump()
        )
    except Exception as e:
        logger.error(f"Error generating recommendation: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error generating recommendation",
            error_code="RECOMMENDATION_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.get("/profile/{user_id}", response_model=InvestorProfile)
async def get_profile(user_id: str):
    """Get current investor profile."""
    logger.info(f"Getting profile for user_id: {user_id}")
    
    # Check in-memory cache first for debugging
    if hasattr(backboard, '_in_memory_storage') and user_id in backboard._in_memory_storage:
        logger.info(f"Profile found in in-memory cache for user_id: {user_id}")
    
    profile = await backboard.get_profile(user_id)
    if not profile:
        logger.error(f"Profile not found for user_id: {user_id}")
        logger.error(f"In-memory storage keys: {list(backboard._in_memory_storage.keys()) if hasattr(backboard, '_in_memory_storage') else 'N/A'}")
        error_response = ErrorResponse(
            error="Profile not found",
            error_code="PROFILE_NOT_FOUND",
            detail=f"Profile not found for user_id: {user_id}. Please initialize profile first using POST /profile/init. If you just created it, the profile may not have been saved to Backboard properly.",
        )
        return JSONResponse(
            status_code=404,
            content=error_response.model_dump()
        )
    logger.info(f"Successfully retrieved profile for user_id: {user_id}")
    return profile


@app.post("/ticker/lookup")
async def lookup_ticker(request: dict):
    """
    Look up a ticker in the database or search web and add it.
    
    Request body: {"ticker": "XXX"}
    Returns success status and message.
    """
    try:
        ticker = request.get("ticker") if isinstance(request, dict) else None
        if not ticker:
            error_response = ErrorResponse(
                error="Missing required parameter",
                error_code="MISSING_PARAMETER",
                detail="ticker parameter required in request body: {\"ticker\": \"XXX\"}",
            )
            return JSONResponse(
                status_code=400,
                content=error_response.model_dump()
            )
        
        from .ticker_lookup import lookup_or_add_ticker
        
        success, message = await lookup_or_add_ticker(ticker)
        
        if success:
            return {
                "success": True,
                "ticker": ticker.upper(),
                "message": message
            }
        else:
            return {
                "success": False,
                "ticker": ticker.upper(),
                "message": message
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error looking up ticker: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error looking up ticker",
            error_code="TICKER_LOOKUP_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/ticker/sectors")
async def get_ticker_sectors(request: Request):
    """
    Get sectors for a list of tickers.
    
    Request body: {"tickers": ["AAPL", "MSFT", ...]}
    Returns mapping of ticker to sector.
    """
    try:
        body = await request.json()
        tickers = body.get("tickers") if isinstance(body, dict) else None
        if not tickers or not isinstance(tickers, list):
            error_response = ErrorResponse(
                error="Missing required parameter",
                error_code="MISSING_PARAMETER",
                detail="tickers parameter required in request body: {\"tickers\": [\"AAPL\", \"MSFT\"]}",
            )
            return JSONResponse(
                status_code=400,
                content=error_response.model_dump()
            )
        
        from .sector_data import get_ticker_sector
        
        result = {}
        for ticker in tickers:
            sector = get_ticker_sector(ticker)
            result[ticker.upper()] = sector or "Unknown"
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticker sectors: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error getting ticker sectors",
            error_code="TICKER_SECTORS_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/ticker/lookup/debug")
async def lookup_ticker_debug(request: dict):
    """
    Debug endpoint for ticker lookup - returns raw AI response.
    """
    import traceback
    
    try:
        ticker = request.get("ticker") if isinstance(request, dict) else None
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker parameter required")
        
        from .ticker_lookup import search_and_classify_ticker
        from .backboard_client import BackboardClient
        
        backboard_client = BackboardClient()
        ticker_upper = ticker.upper()
        
        # Get raw AI response
        assistant_id = await backboard_client._ensure_assistant()
        if not assistant_id:
            return {"error": "Could not get assistant ID"}
        
        from backend.sector_data import load_sectors_data
        sectors_data = load_sectors_data()
        valid_sectors = [s['name'] for s in sectors_data['sectors']]
        sectors_list = ", ".join(valid_sectors)
        
        system_prompt = f"""You are a financial data classifier. You MUST search the web for current information about stock tickers.

Return ONLY valid JSON with this exact structure:
{{
  "ticker": "{ticker_upper}",
  "name": "Company Name",
  "sector": "One of: {sectors_list}",
  "market_cap": "large|medium|small|etf",
  "industry_risk": "low|medium|high|very_high"
}}"""
        
        prompt = f"""SEARCH THE WEB for current information about stock ticker: {ticker_upper}

Extract and return ONLY JSON with:
1. Company name
2. Sector (EXACTLY one of: {sectors_list})
3. Market cap: "large" (>$10B), "medium" ($2-10B), "small" (<$2B), or "etf"
4. Industry risk: "low", "medium", "high", or "very_high"

Return JSON only."""
        
        thread = await backboard_client._sdk_client.create_thread(assistant_id=assistant_id)
        
        # Get thread ID correctly (same as in backboard_client.py)
        thread_id = getattr(thread, 'id', None) or getattr(thread, 'thread_id', None) or str(thread)
        
        # Try to get response, handling validation errors
        response = None
        response_text = ""
        error_info = None
        
        try:
            try:
                response = await backboard_client._sdk_client.add_message(
                    thread_id=thread_id,
                    content=f"{system_prompt}\n\n{prompt}",
                    llm_provider="openai",
                    model_name="gpt-4o-mini",
                    web_search=True
                )
            except TypeError:
                # web_search parameter not supported
                response = await backboard_client._sdk_client.add_message(
                    thread_id=thread_id,
                    content=f"{system_prompt}\n\n{prompt}",
                    llm_provider="openai",
                    model_name="gpt-4o-mini"
                )
        except Exception as e:
            error_info = {
                "error_type": type(e).__name__,
                "error_message": str(e),
            }
            logger.error(f"Error calling add_message: {e}", exc_info=True)
            # Try to extract from error if it has response data
            if hasattr(e, 'response') or hasattr(e, 'args'):
                error_info["error_details"] = str(e.args) if hasattr(e, 'args') else str(e)
        
        # Extract response text
        if response:
            if hasattr(response, 'content'):
                response_text = response.content
            elif hasattr(response, 'latest_message') and hasattr(response.latest_message, 'content'):
                response_text = response.latest_message.content
            elif hasattr(response, 'message') and hasattr(response.message, 'content'):
                response_text = response.message.content
            elif isinstance(response, dict):
                response_text = response.get('content', '') or response.get('text', '') or response.get('latest_message', {}).get('content', '')
            elif hasattr(response, 'text'):
                response_text = response.text
            else:
                response_text = str(response)
        
        result = {
            "ticker": ticker_upper,
            "raw_response": response_text,
            "response_length": len(response_text),
        }
        
        if response:
            result["response_type"] = str(type(response))
            if hasattr(response, '__dict__'):
                result["response_attributes"] = [attr for attr in dir(response) if not attr.startswith('_')]
                result["response_dict"] = {k: str(v)[:200] for k, v in response.__dict__.items()}
        
        if error_info:
            result["error"] = error_info
        
        return result
        
    except Exception as e:
        logger.error(f"Error in debug lookup: {e}", exc_info=True)
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/portfolio/snapshot")
async def save_portfolio_snapshot(request: PortfolioSnapshotRequest):
    """Save portfolio snapshot to Backboard.io memory."""
    try:
        logger.info(f"Saving portfolio snapshot for user_id: {request.user_id}")
        # Get profile for computing metrics (required for proper workflow)
        profile = await backboard.get_profile(request.user_id)
        if not profile:
            logger.warning(f"Profile not found for user {request.user_id} when saving snapshot")
            error_response = ErrorResponse(
                error="Profile not found",
                error_code="PROFILE_NOT_FOUND",
                detail=f"Profile not found for user_id: {request.user_id}. Please initialize your profile first using POST /profile/init. The profile is required to carry context through the workflow (analyze -> recommend -> snapshot).",
            )
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump()
            )
        
        logger.info(f"Profile found for user {request.user_id}, computing metrics with constraints")
        
        # Build portfolio input
        portfolio = PortfolioInput(
            holdings=request.holdings,
            cash_weight=request.cash_weight,
        )
        
        # Compute metrics with profile (required for constraint checking)
        metrics = compute_metrics(portfolio, profile)
        
        # Create snapshot
        timestamp = datetime.utcnow().isoformat()
        snapshot_id = timestamp
        snapshot = {
            "snapshot_id": snapshot_id,
            "timestamp": timestamp,
            "user_id": request.user_id,
            "holdings": [h.model_dump() for h in request.holdings],
            "cash_weight": request.cash_weight,
            "metrics": metrics.model_dump()
        }
        
        # Store in Backboard.io memory
        memory_key = f"portfolio_snapshot:{snapshot_id}"
        await backboard.append_memory(
            request.user_id,
            memory_key,
            snapshot
        )
        
        logger.info(f"Successfully saved portfolio snapshot for user: {request.user_id}, snapshot_id: {snapshot_id}")
        return {"success": True, "snapshot_id": snapshot_id, "timestamp": timestamp}
    except ValueError as e:
        error_response = ErrorResponse(
            error="Validation error",
            error_code="VALIDATION_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=400,
            content=error_response.model_dump()
        )
    except Exception as e:
        logger.error(f"Error saving portfolio snapshot: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error saving portfolio snapshot",
            error_code="SNAPSHOT_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.get("/portfolio/history/{user_id}", response_model=PortfolioHistoryResponse)
async def get_portfolio_history(user_id: str):
    """Get portfolio history from Backboard.io memory."""
    try:
        # Retrieve all snapshots
        memories = await backboard.get_memories(user_id, key_prefix="portfolio_snapshot:")
        
        # Convert to PortfolioSnapshot objects
        snapshots = []
        for memory in memories:
            try:
                content = memory.get('content', {}) if isinstance(memory, dict) else memory
                if isinstance(content, str):
                    import json
                    content = json.loads(content)
                
                # Reconstruct holdings
                from .models import Holding
                holdings = [Holding(**h) for h in content.get('holdings', [])]
                
                # Reconstruct metrics
                metrics_dict = content.get('metrics', {})
                metrics = PortfolioMetrics(**metrics_dict)
                
                snapshot = PortfolioSnapshot(
                    snapshot_id=content.get('snapshot_id', memory.get('timestamp', '')),
                    timestamp=content.get('timestamp', memory.get('timestamp', '')),
                    user_id=content.get('user_id', user_id),
                    holdings=holdings,
                    cash_weight=content.get('cash_weight', 0.0),
                    metrics=metrics
                )
                snapshots.append(snapshot)
            except Exception as e:
                logger.warning(f"Error parsing snapshot: {e}, skipping")
                continue
        
        # Sort by timestamp descending (newest first)
        snapshots.sort(key=lambda x: x.timestamp, reverse=True)
        
        return PortfolioHistoryResponse(
            user_id=user_id,
            snapshots=snapshots
        )
    except Exception as e:
        logger.error(f"Error retrieving portfolio history: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error retrieving portfolio history",
            error_code="HISTORY_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )


@app.post("/portfolio/compare", response_model=PortfolioComparison)
async def compare_portfolios(request: CompareRequest):
    """Compare current vs recommended portfolio."""
    try:
        # Get profile for computing metrics
        profile = await backboard.get_profile(request.user_id)
        if not profile:
            error_response = ErrorResponse(
                error="Profile not found",
                error_code="PROFILE_NOT_FOUND",
                detail=f"Profile not found for user_id: {request.user_id}. Please initialize profile first.",
            )
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump()
            )
        
        # Compute metrics for both portfolios
        current_metrics = compute_metrics(request.current_portfolio, profile)
        recommended_metrics = compute_metrics(request.recommended_portfolio, profile)
        
        # Calculate differences
        differences = {
            "holdings_change": len(request.recommended_portfolio.holdings) - len(request.current_portfolio.holdings),
            "risk_change": recommended_metrics.herfindahl_index - current_metrics.herfindahl_index,
            "top_1_weight_change": recommended_metrics.top_1_weight - current_metrics.top_1_weight,
            "top_3_weight_change": recommended_metrics.top_3_weight - current_metrics.top_3_weight,
            "top_5_weight_change": recommended_metrics.top_5_weight - current_metrics.top_5_weight,
            "cash_weight_change": request.recommended_portfolio.cash_weight - request.current_portfolio.cash_weight,
            "sector_allocation_changes": {}
        }
        
        # Compare sector allocations
        current_sectors = current_metrics.sector_allocation
        recommended_sectors = recommended_metrics.sector_allocation
        all_sectors = set(current_sectors.keys()) | set(recommended_sectors.keys())
        
        for sector in all_sectors:
            current_weight = current_sectors.get(sector, 0.0)
            recommended_weight = recommended_sectors.get(sector, 0.0)
            diff = recommended_weight - current_weight
            if abs(diff) > 0.001:  # Only include meaningful changes
                differences["sector_allocation_changes"][sector] = {
                    "current": current_weight,
                    "recommended": recommended_weight,
                    "change": diff
                }
        
        return PortfolioComparison(
            current=current_metrics,
            recommended=recommended_metrics,
            differences=differences
        )
    except ValueError as e:
        error_response = ErrorResponse(
            error="Validation error",
            error_code="VALIDATION_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=400,
            content=error_response.model_dump()
        )
    except Exception as e:
        logger.error(f"Error comparing portfolios: {e}", exc_info=True)
        error_response = ErrorResponse(
            error="Error comparing portfolios",
            error_code="COMPARISON_ERROR",
            detail=str(e),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump()
        )

