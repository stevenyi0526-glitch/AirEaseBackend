"""
AirEase Backend - User Routes
Favorites, travelers, search history, and user-specific endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db, UserDB, FavoriteDB, TravelerInfoDB, SearchHistoryDB
from app.models import (
    FavoriteCreate, FavoriteResponse,
    TravelerCreate, TravelerUpdate, TravelerResponse,
    SearchHistoryCreate, SearchHistoryResponse
)
from app.routes.auth import require_auth

router = APIRouter(prefix="/v1/users", tags=["Users"])


# ============================================================
# Favorites Endpoints
# ============================================================

@router.get(
    "/favorites",
    response_model=List[FavoriteResponse],
    summary="Get user favorites",
    description="Get all favorite flights for the current user"
)
async def get_favorites(
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all favorites for the current user."""
    favorites = db.query(FavoriteDB).filter(
        FavoriteDB.user_id == current_user.user_id
    ).order_by(FavoriteDB.created_at.desc()).all()
    
    return [FavoriteResponse(
        id=f.id,
        flightId=f.flight_id,
        flightNumber=f.flight_number,
        airline=f.airline,
        departureCity=f.departure_city,
        arrivalCity=f.arrival_city,
        departureTime=f.departure_time,
        price=f.price,
        score=f.score,
        createdAt=f.created_at
    ) for f in favorites]


@router.post(
    "/favorites",
    response_model=FavoriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add favorite",
    description="Add a flight to favorites"
)
async def add_favorite(
    favorite_data: FavoriteCreate,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Add a flight to user favorites."""
    # Check if already favorited
    existing = db.query(FavoriteDB).filter(
        FavoriteDB.user_id == current_user.user_id,
        FavoriteDB.flight_id == favorite_data.flight_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Flight already in favorites"
        )
    
    # Create favorite
    db_favorite = FavoriteDB(
        user_id=current_user.user_id,
        flight_id=favorite_data.flight_id,
        flight_number=favorite_data.flight_number,
        airline=favorite_data.airline,
        departure_city=favorite_data.departure_city,
        arrival_city=favorite_data.arrival_city,
        departure_time=favorite_data.departure_time,
        price=favorite_data.price,
        score=favorite_data.score
    )
    
    db.add(db_favorite)
    db.commit()
    db.refresh(db_favorite)
    
    return FavoriteResponse(
        id=db_favorite.id,
        flightId=db_favorite.flight_id,
        flightNumber=db_favorite.flight_number,
        airline=db_favorite.airline,
        departureCity=db_favorite.departure_city,
        arrivalCity=db_favorite.arrival_city,
        departureTime=db_favorite.departure_time,
        price=db_favorite.price,
        score=db_favorite.score,
        createdAt=db_favorite.created_at
    )


@router.delete(
    "/favorites/{flight_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove favorite",
    description="Remove a flight from favorites"
)
async def remove_favorite(
    flight_id: str,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Remove a flight from user favorites."""
    favorite = db.query(FavoriteDB).filter(
        FavoriteDB.user_id == current_user.user_id,
        FavoriteDB.flight_id == flight_id
    ).first()
    
    if not favorite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favorite not found"
        )
    
    db.delete(favorite)
    db.commit()


# ============================================================
# Travelers Endpoints
# ============================================================

@router.get(
    "/travelers",
    response_model=List[TravelerResponse],
    summary="Get travelers",
    description="Get all saved travelers for the current user's family"
)
async def get_travelers(
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all travelers for the current user's family."""
    travelers = db.query(TravelerInfoDB).filter(
        TravelerInfoDB.family_id == current_user.family_id
    ).order_by(TravelerInfoDB.created_at.desc()).all()
    
    return [TravelerResponse(
        id=t.id,
        familyId=t.family_id,
        firstName=t.first_name,
        middleName=t.middle_name,
        lastName=t.last_name,
        passportNumber=t.passport_number,
        dob=t.dob,
        nationality=t.nationality,
        gender=t.gender,
        isPrimary=t.is_primary,
        createdAt=t.created_at
    ) for t in travelers]


@router.post(
    "/travelers",
    response_model=TravelerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add traveler",
    description="Add a new traveler to the family"
)
async def add_traveler(
    traveler_data: TravelerCreate,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Add a new traveler to the user's family."""
    db_traveler = TravelerInfoDB(
        family_id=current_user.family_id,
        first_name=traveler_data.first_name,
        middle_name=traveler_data.middle_name,
        last_name=traveler_data.last_name,
        passport_number=traveler_data.passport_number,
        dob=traveler_data.dob,
        nationality=traveler_data.nationality,
        gender=traveler_data.gender,
        is_primary=False
    )
    
    db.add(db_traveler)
    db.commit()
    db.refresh(db_traveler)
    
    return TravelerResponse(
        id=db_traveler.id,
        familyId=db_traveler.family_id,
        firstName=db_traveler.first_name,
        middleName=db_traveler.middle_name,
        lastName=db_traveler.last_name,
        passportNumber=db_traveler.passport_number,
        dob=db_traveler.dob,
        nationality=db_traveler.nationality,
        gender=db_traveler.gender,
        isPrimary=db_traveler.is_primary,
        createdAt=db_traveler.created_at
    )


@router.put(
    "/travelers/{traveler_id}",
    response_model=TravelerResponse,
    summary="Update traveler",
    description="Update a traveler's information"
)
async def update_traveler(
    traveler_id: int,
    update_data: TravelerUpdate,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Update a traveler in the user's family."""
    traveler = db.query(TravelerInfoDB).filter(
        TravelerInfoDB.id == traveler_id,
        TravelerInfoDB.family_id == current_user.family_id
    ).first()
    
    if not traveler:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Traveler not found"
        )
    
    if update_data.first_name is not None:
        traveler.first_name = update_data.first_name
    if update_data.middle_name is not None:
        traveler.middle_name = update_data.middle_name
    if update_data.last_name is not None:
        traveler.last_name = update_data.last_name
    if update_data.passport_number is not None:
        traveler.passport_number = update_data.passport_number
    if update_data.dob is not None:
        traveler.dob = update_data.dob
    if update_data.nationality is not None:
        traveler.nationality = update_data.nationality
    if update_data.gender is not None:
        traveler.gender = update_data.gender
    
    db.commit()
    db.refresh(traveler)
    
    return TravelerResponse(
        id=traveler.id,
        familyId=traveler.family_id,
        firstName=traveler.first_name,
        middleName=traveler.middle_name,
        lastName=traveler.last_name,
        passportNumber=traveler.passport_number,
        dob=traveler.dob,
        nationality=traveler.nationality,
        gender=traveler.gender,
        isPrimary=traveler.is_primary,
        createdAt=traveler.created_at
    )


@router.delete(
    "/travelers/{traveler_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete traveler",
    description="Delete a traveler from the family"
)
async def delete_traveler(
    traveler_id: int,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete a traveler from the user's family."""
    traveler = db.query(TravelerInfoDB).filter(
        TravelerInfoDB.id == traveler_id,
        TravelerInfoDB.family_id == current_user.family_id
    ).first()
    
    if not traveler:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Traveler not found"
        )
    
    # Don't allow deleting primary traveler (account owner)
    if traveler.is_primary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete primary account holder"
        )
    
    db.delete(traveler)
    db.commit()


# ============================================================
# Search History Endpoints
# ============================================================

@router.get(
    "/search-history",
    response_model=List[SearchHistoryResponse],
    summary="Get search history",
    description="Get the user's flight search history"
)
async def get_search_history(
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get all search history for the current user."""
    history = db.query(SearchHistoryDB).filter(
        SearchHistoryDB.user_id == current_user.user_id
    ).order_by(SearchHistoryDB.created_at.desc()).limit(20).all()
    
    return [SearchHistoryResponse(
        id=h.id,
        departure_city=h.departure_city,
        arrival_city=h.arrival_city,
        departure_date=h.departure_date,
        return_date=h.return_date,
        passengers=h.passengers,
        cabin_class=h.cabin_class,
        created_at=h.created_at
    ) for h in history]


@router.post(
    "/search-history",
    response_model=SearchHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add search history",
    description="Add a flight search to history"
)
async def add_search_history(
    search_data: SearchHistoryCreate,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Add a flight search to user's history."""
    # Check for duplicate recent search (same route and dates within last hour)
    from datetime import datetime, timedelta
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    existing = db.query(SearchHistoryDB).filter(
        SearchHistoryDB.user_id == current_user.user_id,
        SearchHistoryDB.departure_city == search_data.departure_city,
        SearchHistoryDB.arrival_city == search_data.arrival_city,
        SearchHistoryDB.departure_date == search_data.departure_date,
        SearchHistoryDB.created_at >= one_hour_ago
    ).first()
    
    if existing:
        # Update existing entry
        existing.return_date = search_data.return_date
        existing.passengers = search_data.passengers
        existing.cabin_class = search_data.cabin_class
        existing.created_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return SearchHistoryResponse(
            id=existing.id,
            departure_city=existing.departure_city,
            arrival_city=existing.arrival_city,
            departure_date=existing.departure_date,
            return_date=existing.return_date,
            passengers=existing.passengers,
            cabin_class=existing.cabin_class,
            created_at=existing.created_at
        )
    
    # Create new history entry
    db_history = SearchHistoryDB(
        user_id=current_user.user_id,
        departure_city=search_data.departure_city,
        arrival_city=search_data.arrival_city,
        departure_date=search_data.departure_date,
        return_date=search_data.return_date,
        passengers=search_data.passengers,
        cabin_class=search_data.cabin_class
    )
    
    db.add(db_history)
    db.commit()
    db.refresh(db_history)
    
    return SearchHistoryResponse(
        id=db_history.id,
        departure_city=db_history.departure_city,
        arrival_city=db_history.arrival_city,
        departure_date=db_history.departure_date,
        return_date=db_history.return_date,
        passengers=db_history.passengers,
        cabin_class=db_history.cabin_class,
        created_at=db_history.created_at
    )


@router.delete(
    "/search-history/{history_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete search history item",
    description="Delete a specific search history item"
)
async def delete_search_history_item(
    history_id: int,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Delete a specific search history item."""
    history_item = db.query(SearchHistoryDB).filter(
        SearchHistoryDB.id == history_id,
        SearchHistoryDB.user_id == current_user.user_id
    ).first()
    
    if not history_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search history item not found"
        )
    
    db.delete(history_item)
    db.commit()


@router.delete(
    "/search-history",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear search history",
    description="Clear all search history for the user"
)
async def clear_search_history(
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Clear all search history for the current user."""
    db.query(SearchHistoryDB).filter(
        SearchHistoryDB.user_id == current_user.user_id
    ).delete()
    db.commit()
