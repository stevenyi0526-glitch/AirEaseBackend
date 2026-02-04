#!/usr/bin/env python3
"""
AirEase Backend Runner
启动后端服务
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print("🚀 Starting AirEase Backend Server...")
    print(f"   URL: http://{settings.host}:{settings.port}")
    print(f"   Docs: http://localhost:{settings.port}/docs")
    print()
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )
