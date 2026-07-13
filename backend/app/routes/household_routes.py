from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..errors import ConflictError, DomainError, NotFoundError
from ..models import Household, HouseholdMember, MealAllocation, Restriction, TargetProfile, UserRole
from ..schemas import (
    MemberCreate,
    MemberOut,
    MemberUpdate,
    RestrictionIn,
    TargetProfileIn,
    TargetProfileOut,
)

router = APIRouter(tags=["household"])


@router.get("/households/current")
def current_household(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    household = db.get(Household, context.user.household_id)
    return {"id": household.id, "name": household.name, "timezone": household.timezone, "version": household.version}


@router.get("/household-members", response_model=list[MemberOut])
def list_members(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    return db.scalars(
        select(HouseholdMember)
        .where(HouseholdMember.household_id == context.user.household_id)
        .order_by(HouseholdMember.name)
    ).all()


@router.post("/household-members", response_model=MemberOut, status_code=201)
def create_member(
    payload: MemberCreate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if context.user.role != UserRole.OWNER.value:
        raise DomainError("OWNER_REQUIRED", "Only the owner can create household members", 403)
    member = HouseholdMember(household_id=context.user.household_id, name=payload.name)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.patch("/household-members/{member_id}", response_model=MemberOut)
def update_member(
    member_id: str,
    payload: MemberUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    if context.user.role != UserRole.OWNER.value and context.user.member_id != member.id:
        raise DomainError("MEMBER_EDIT_FORBIDDEN", "You may edit only your linked profile", 403)
    if member.version != payload.expected_version:
        raise ConflictError()
    if payload.name is not None:
        member.name = payload.name
    if payload.active is not None:
        if context.user.role != UserRole.OWNER.value:
            raise DomainError("OWNER_REQUIRED", "Only the owner can change active status", 403)
        member.active = payload.active
    member.version += 1
    db.commit()
    db.refresh(member)
    return member


def _target_out(db: Session, target: TargetProfile) -> TargetProfileOut:
    allocations = db.scalars(
        select(MealAllocation).where(MealAllocation.target_profile_id == target.id)
    ).all()
    return TargetProfileOut.model_validate(
        {
            **{column.name: getattr(target, column.name) for column in target.__table__.columns},
            "allocations": allocations,
        }
    )


@router.get("/household-members/{member_id}/target", response_model=TargetProfileOut)
def get_target(
    member_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    target = db.scalar(select(TargetProfile).where(TargetProfile.member_id == member.id))
    if target is None:
        raise NotFoundError("Target profile")
    return _target_out(db, target)


@router.put("/household-members/{member_id}/target", response_model=TargetProfileOut)
def set_target(
    member_id: str,
    payload: TargetProfileIn,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    if context.user.role != UserRole.OWNER.value and context.user.member_id != member.id:
        raise DomainError("TARGET_EDIT_FORBIDDEN", "You may edit only your linked target", 403)
    target = db.scalar(select(TargetProfile).where(TargetProfile.member_id == member.id))
    data = payload.model_dump(exclude={"allocations"})
    data["mode"] = payload.mode.value
    if target is None:
        target = TargetProfile(member_id=member.id, **data)
        db.add(target)
        db.flush()
    else:
        for key, value in data.items():
            setattr(target, key, value)
        target.version += 1
        db.execute(delete(MealAllocation).where(MealAllocation.target_profile_id == target.id))
    for allocation in payload.allocations:
        db.add(
            MealAllocation(
                target_profile_id=target.id,
                meal_type=allocation.meal_type.lower(),
                percentage=allocation.percentage,
            )
        )
    db.commit()
    db.refresh(target)
    return _target_out(db, target)


@router.get("/household-members/{member_id}/restrictions")
def list_restrictions(
    member_id: str,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    return db.scalars(select(Restriction).where(Restriction.member_id == member_id)).all()


@router.post("/household-members/{member_id}/restrictions", status_code=201)
def add_restriction(
    member_id: str,
    payload: RestrictionIn,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    if context.user.role != UserRole.OWNER.value and context.user.member_id != member.id:
        raise DomainError("MEMBER_EDIT_FORBIDDEN", "You may edit only your linked profile", 403)
    restriction = Restriction(
        member_id=member.id,
        kind=payload.kind,
        value=payload.value.strip().lower(),
        hard=payload.hard or payload.kind in ("allergy", "exclude"),
    )
    db.add(restriction)
    db.commit()
    db.refresh(restriction)
    return restriction
