"""
AirEase Backend - Main Application
FastAPI 应用入口
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from app.config import settings
from app.routes.flights import router as flights_router
from app.routes.ai import router as ai_router
from app.routes.auth import router as auth_router
from app.routes.users import router as users_router
from app.routes.cities import router as cities_router
from app.routes.airports import router as airports_router
from app.routes.recommendations import router as recommendations_router
from app.routes.reports import router as reports_router
from app.routes.booking import router as booking_router
from app.routes.autocomplete import router as autocomplete_router
from app.routes.user_preferences import router as user_preferences_router
from app.routes.exchange_rates import router as exchange_rates_router
from app.routes.aircraft import router as aircraft_router
# PAUSED: SeatMap disabled until Amadeus production access (test env = cached/mock data)
# from app.routes.seatmap import router as seatmap_router
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    print("🛫 AirEase Backend starting...")
    print(f"   Debug mode: {settings.debug}")
    print(f"   SerpAPI (Flights): {'✓ configured' if settings.serpapi_key else '✗ not configured'}")
    print(f"   Amadeus (Autocomplete): {'✓ configured' if settings.amadeus_api_key else '✗ not configured'}")
    print(f"   Gemini API: {'✓ configured' if settings.gemini_api_key else '✗ not configured'}")
    print(f"   Amadeus API: {'✓ configured' if settings.amadeus_api_key else '✗ not configured'}")
    print(f"   Amadeus SeatMap: ⏸ PAUSED (test env = cached data, re-enable with production key)")
    print(f"   Google Places API: {'✓ configured' if settings.google_places_api_key else '✗ not configured (using local fallback)'}")
    print(f"   JWT Auth: ✓ configured")
    print(f"   Email Notifications: {'✓ configured → ' + settings.admin_email if settings.smtp_host and settings.admin_email else '✗ not configured'}")
    print(f"   PostgreSQL: {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")

    # Initialize database
    print("   Initializing database...")
    init_db()
    print("   Database: ✓ ready")

    yield
    
    # Shutdown
    print("🛬 AirEase Backend shutting down...")
    from app.services.gemini_service import gemini_service
    await gemini_service.close()


# Create FastAPI application
app = FastAPI(
    title="AirEase API",
    description="""
    ## AirEase 航班体验优选 API
    
    提供航班搜索、评分和AI智能搜索服务。
    
    ### 功能模块
    
    - **航班搜索**: 根据城市、日期、舱位搜索航班
    - **航班详情**: 获取航班评分、设施、价格历史
    - **AI智能搜索**: 自然语言解析航班查询
    
    ### 评分维度
    
    - 安全性 (Safety): 航司安全记录、机型可靠性
    - 舒适度 (Comfort): 座椅空间、机舱环境
    - 服务 (Service): 餐食、娱乐、机组服务
    - 性价比 (Value): 价格与服务的综合评估
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Middleware - Allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must be False when using wildcard "*" for origins
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))
    return response


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred",
            "code": 500
        }
    )


# Include routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(cities_router)
app.include_router(airports_router)
app.include_router(autocomplete_router)
app.include_router(flights_router)
app.include_router(booking_router)
# Price insights removed - no longer needed
app.include_router(ai_router)
app.include_router(recommendations_router)
app.include_router(user_preferences_router)
app.include_router(reports_router)
app.include_router(exchange_rates_router)
app.include_router(aircraft_router)
# PAUSED: SeatMap disabled until Amadeus production access
# app.include_router(seatmap_router)


# Root endpoint
@app.get("/", tags=["Health"])
async def root():
    """API 根路径"""
    return {
        "name": "AirEase API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "services": {
            "api": "ok",
            "gemini": "ok" if settings.gemini_api_key else "not_configured",
            "amadeus": "ok" if settings.amadeus_api_key else "not_configured"
        }
    }


# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
