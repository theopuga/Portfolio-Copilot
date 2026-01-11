"""Pydantic models for the portfolio copilot."""

import re
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class Objective(BaseModel):
    """Investment objective."""
    type: Literal["growth", "income", "balanced"]
    notes: str = ""


class Constraints(BaseModel):
    """Portfolio constraints."""
    max_holdings: int = Field(default=20, ge=1, le=100)
    max_position_pct: float = Field(default=25.0, ge=1.0, le=100.0)
    exclusions: list[str] = Field(default_factory=list)
    options_allowed: bool = False
    leverage_allowed: bool = False


class Preferences(BaseModel):
    """Investment preferences."""
    sectors_like: list[str] = Field(default_factory=list)
    sectors_avoid: list[str] = Field(default_factory=list)
    regions_like: list[str] = Field(default_factory=list)


class InvestorProfile(BaseModel):
    """User's investment profile stored in Backboard memory."""
    user_id: str
    objective: Objective
    horizon_months: int = Field(ge=0, le=600)
    risk_score: int = Field(default=50, ge=0, le=100)
    constraints: Constraints = Field(default_factory=Constraints)
    preferences: Preferences = Field(default_factory=Preferences)
    rebalance_frequency: Literal["monthly", "quarterly", "annual"] = "quarterly"
    last_updated: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Holding(BaseModel):
    """Single portfolio holding."""
    ticker: str = Field(..., min_length=1, max_length=5, description="Stock ticker symbol (1-5 characters, alphanumeric)")
    weight: float = Field(ge=0.0, le=1.0)
    
    @field_validator('ticker')
    @classmethod
    def validate_ticker_format(cls, v: str) -> str:
        """Validate ticker format: uppercase, alphanumeric, 1-5 characters."""
        if not v:
            raise ValueError("Ticker cannot be empty")
        # Normalize to uppercase
        v = v.upper().strip()
        # Check format: alphanumeric only, 1-5 characters
        if not re.match(r'^[A-Z0-9]{1,5}$', v):
            raise ValueError(f"Ticker must be 1-5 alphanumeric characters, got: {v}")
        return v


class PortfolioInput(BaseModel):
    """Portfolio input from user."""
    holdings: list[Holding]
    cash_weight: float = Field(default=0.0, ge=0.0, le=1.0)


class ErrorResponse(BaseModel):
    """Unified error response model."""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code for programmatic handling")
    detail: Optional[str] = Field(None, description="Additional error details")
    version: str = Field(default="1.0.0", description="API version")


class TickerLookupResult(BaseModel):
    """Result of a ticker lookup operation."""
    ticker: str = Field(..., description="Ticker symbol (uppercase)")
    success: bool = Field(..., description="Whether lookup was successful")
    message: str = Field(..., description="Lookup result message")


class PortfolioMetrics(BaseModel):
    """Computed portfolio metrics."""
    model_config = ConfigDict(serialize_defaults=True)
    
    total_holdings: int
    top_1_weight: float
    top_3_weight: float
    top_5_weight: float
    herfindahl_index: float
    constraint_violations: list[str] = Field(default_factory=list)
    drift_summary: Optional[str] = None
    ticker_lookups: list[TickerLookupResult] = Field(default_factory=list, description="Results of ticker lookup operations")
    sector_allocation: dict[str, float] = Field(default_factory=dict, description="Sector allocation breakdown (sector name -> weight)")
    ticker_sectors: dict[str, str] = Field(default_factory=dict, description="Mapping of ticker to sector name")
    version: str = Field(default="1.0.0", description="API version")


class TargetAllocation(BaseModel):
    """Target allocation sleeves."""
    cash: float = Field(ge=0.0, le=1.0)
    core_equity: float = Field(ge=0.0, le=1.0)
    thematic_sectors: float = Field(ge=0.0, le=1.0)  # Allocation to preferred sectors
    defensive: float = Field(ge=0.0, le=1.0)


class RebalanceAction(BaseModel):
    """Single rebalance action."""
    action: Literal["BUY", "SELL"]
    ticker: str
    delta_weight: float


class RebalancePlan(BaseModel):
    """Rebalance plan with actions and explanations."""
    actions: list[RebalanceAction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProfileInitRequest(BaseModel):
    """Request to initialize profile."""
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    onboarding_text: str = Field(..., min_length=10, max_length=20000, description="Onboarding text describing investment profile (10-20000 characters)")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v


class ProfileUpdateRequest(BaseModel):
    """Request to update profile."""
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    update_text: str = Field(..., min_length=10, max_length=20000, description="Update text describing profile changes (10-20000 characters)")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v


class AnalyzeRequest(BaseModel):
    """Request to analyze portfolio."""
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    holdings: list[Holding] = Field(..., min_length=0, description="List of portfolio holdings")
    cash_weight: float = Field(default=0.0, ge=0.0, le=1.0, description="Cash allocation weight (0.0-1.0)")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v
    
    @field_validator('holdings')
    @classmethod
    def validate_no_duplicate_tickers(cls, v: list[Holding]) -> list[Holding]:
        """Validate no duplicate tickers in holdings."""
        tickers = [holding.ticker.upper() for holding in v]
        duplicates = [ticker for ticker in set(tickers) if tickers.count(ticker) > 1]
        if duplicates:
            raise ValueError(f"Duplicate tickers found in holdings: {', '.join(duplicates)}")
        return v


class RecommendRequest(BaseModel):
    """Request for rebalance recommendation.
    
    If holdings is empty/None, constructs a new portfolio from scratch.
    Otherwise, rebalances the existing portfolio.
    """
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    holdings: list[Holding] = Field(default_factory=list, description="List of portfolio holdings (empty for new portfolio)")
    cash_weight: float = Field(default=0.0, ge=0.0, le=1.0, description="Cash allocation weight (0.0-1.0)")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v
    
    @field_validator('holdings')
    @classmethod
    def validate_no_duplicate_tickers(cls, v: list[Holding]) -> list[Holding]:
        """Validate no duplicate tickers in holdings."""
        if not v:
            return v  # Empty holdings are allowed for new portfolio construction
        tickers = [holding.ticker.upper() for holding in v]
        duplicates = [ticker for ticker in set(tickers) if tickers.count(ticker) > 1]
        if duplicates:
            raise ValueError(f"Duplicate tickers found in holdings: {', '.join(duplicates)}")
        return v


class RecommendationResponse(BaseModel):
    """Full recommendation response."""
    model_config = ConfigDict(serialize_defaults=True)
    
    profile: InvestorProfile
    metrics: PortfolioMetrics
    plan: RebalancePlan
    explanation: str
    operation_type: Literal["construct", "rebalance"] = Field(..., description="Type of operation: 'construct' for new portfolio, 'rebalance' for existing portfolio")
    version: str = Field(default="1.0.0", description="API version")


class PortfolioSnapshotRequest(BaseModel):
    """Request to save portfolio snapshot."""
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    holdings: list[Holding] = Field(..., description="List of portfolio holdings")
    cash_weight: float = Field(default=0.0, ge=0.0, le=1.0, description="Cash allocation weight (0.0-1.0)")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v


class PortfolioSnapshot(BaseModel):
    """Portfolio snapshot stored in memory."""
    snapshot_id: str = Field(..., description="Snapshot identifier (timestamp)")
    timestamp: str = Field(..., description="ISO timestamp when snapshot was created")
    user_id: str = Field(..., description="User identifier")
    holdings: list[Holding] = Field(..., description="List of portfolio holdings")
    cash_weight: float = Field(..., description="Cash allocation weight")
    metrics: PortfolioMetrics = Field(..., description="Computed portfolio metrics")


class PortfolioHistoryResponse(BaseModel):
    """Response containing portfolio history."""
    user_id: str = Field(..., description="User identifier")
    snapshots: list[PortfolioSnapshot] = Field(default_factory=list, description="List of portfolio snapshots, sorted by timestamp (newest first)")


class CompareRequest(BaseModel):
    """Request to compare two portfolios."""
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    current_portfolio: PortfolioInput = Field(..., description="Current portfolio")
    recommended_portfolio: PortfolioInput = Field(..., description="Recommended portfolio")
    
    @field_validator('user_id')
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Validate user_id format: alphanumeric, underscore, dash only."""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("user_id must contain only alphanumeric characters, underscores, or dashes")
        return v


class PortfolioComparison(BaseModel):
    """Comparison between two portfolios."""
    current: PortfolioMetrics = Field(..., description="Current portfolio metrics")
    recommended: PortfolioMetrics = Field(..., description="Recommended portfolio metrics")
    differences: dict = Field(..., description="Key differences between portfolios")

