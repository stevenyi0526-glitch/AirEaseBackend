"""
AirEase Backend - Reports Routes
反馈与纠错管理 API endpoints
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from sqlalchemy.orm import Session
import json

from app.database import get_db, ReportDB
from app.models import ReportCreate, ReportResponse, ReportCategoryInfo
from app.services.email_service import email_service

router = APIRouter(prefix="/reports", tags=["Feedback & Reports 反馈与纠错"])


# Category labels mapping
CATEGORY_LABELS = {
    "aircraft_mismatch": ("机型不符", "Aircraft Type Mismatch"),
    "missing_facilities": ("设施缺失", "Missing Facilities"),
    "price_error": ("价格错误", "Price Error"),
    "flight_info_error": ("航班信息错误", "Flight Info Error"),
    "time_inaccurate": ("时间不准确", "Incorrect Time"),
    "other": ("其他", "Other"),
}

STATUS_LABELS = {
    "pending": ("待处理", "Pending"),
    "reviewed": ("已审核", "Reviewed"),
    "resolved": ("已解决", "Resolved"),
    "dismissed": ("已驳回", "Dismissed"),
}


@router.get("/categories", response_model=List[ReportCategoryInfo])
async def get_report_categories():
    """
    获取所有反馈类别
    Get all available report categories
    """
    categories = []
    for value, (label_cn, label_en) in CATEGORY_LABELS.items():
        categories.append(ReportCategoryInfo(
            value=value,
            label=label_cn,
            labelEn=label_en,
            description=None
        ))
    return categories


@router.post("/", response_model=ReportResponse)
async def create_report(
    report: ReportCreate, 
    user_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    提交反馈报告
    Submit a feedback/error report
    
    Categories:
    - aircraft_mismatch: 机型不符
    - missing_facilities: 设施缺失
    - price_error: 价格错误
    - flight_info_error: 航班信息错误
    - time_inaccurate: 时间不准确
    - other: 其他
    """
    try:
        # Serialize flight_info to JSON string if present
        flight_info_json = json.dumps(report.flight_info) if report.flight_info else None
        
        # Create new report
        new_report = ReportDB(
            user_id=user_id,
            user_email=report.user_email,
            category=report.category.value,
            content=report.content,
            flight_id=report.flight_id,
            flight_info=flight_info_json,
            status="pending",
        )
        
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        
        # Send email notification asynchronously (don't block response)
        try:
            await email_service.send_report_notification(
                report_id=new_report.id,
                user_email=report.user_email,
                category=report.category.value,
                content=report.content,
                flight_id=report.flight_id,
                flight_info=report.flight_info,
            )
        except Exception as e:
            print(f"Email notification failed (non-blocking): {e}")
        
        # Build response
        category_label = CATEGORY_LABELS.get(new_report.category, ("未知", "Unknown"))[0]
        status_label = STATUS_LABELS.get(new_report.status, ("未知", "Unknown"))[0]
        
        return ReportResponse(
            id=new_report.id,
            userId=new_report.user_id,
            userEmail=new_report.user_email,
            category=new_report.category,
            categoryLabel=category_label,
            content=new_report.content,
            flightId=new_report.flight_id,
            flightInfo=json.loads(new_report.flight_info) if new_report.flight_info else None,
            status=new_report.status,
            statusLabel=status_label,
            adminNotes=new_report.admin_notes,
            createdAt=new_report.created_at,
            updatedAt=new_report.updated_at,
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create report: {str(e)}")


@router.get("/", response_model=List[ReportResponse])
async def get_reports(
    user_email: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    获取反馈报告列表
    Get list of reports (optionally filtered by user_email, category, or status)
    """
    query = db.query(ReportDB)
    
    if user_email:
        query = query.filter(ReportDB.user_email == user_email)
    
    if category:
        query = query.filter(ReportDB.category == category)
    
    if status:
        query = query.filter(ReportDB.status == status)
    
    reports_db = query.order_by(ReportDB.created_at.desc()).offset(offset).limit(limit).all()
    
    reports = []
    for row in reports_db:
        category_label = CATEGORY_LABELS.get(row.category, ("未知", "Unknown"))[0]
        status_label = STATUS_LABELS.get(row.status, ("未知", "Unknown"))[0]
        
        reports.append(ReportResponse(
            id=row.id,
            userId=row.user_id,
            userEmail=row.user_email,
            category=row.category,
            categoryLabel=category_label,
            content=row.content,
            flightId=row.flight_id,
            flightInfo=json.loads(row.flight_info) if row.flight_info else None,
            status=row.status,
            statusLabel=status_label,
            adminNotes=row.admin_notes,
            createdAt=row.created_at,
            updatedAt=row.updated_at,
        ))
    
    return reports


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(report_id: int, db: Session = Depends(get_db)):
    """
    获取单个反馈报告详情
    Get a single report by ID
    """
    row = db.query(ReportDB).filter(ReportDB.id == report_id).first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    
    category_label = CATEGORY_LABELS.get(row.category, ("未知", "Unknown"))[0]
    status_label = STATUS_LABELS.get(row.status, ("未知", "Unknown"))[0]
    
    return ReportResponse(
        id=row.id,
        userId=row.user_id,
        userEmail=row.user_email,
        category=row.category,
        categoryLabel=category_label,
        content=row.content,
        flightId=row.flight_id,
        flightInfo=json.loads(row.flight_info) if row.flight_info else None,
        status=row.status,
        statusLabel=status_label,
        adminNotes=row.admin_notes,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )
