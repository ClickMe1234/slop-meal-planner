from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_auth_context, require_csrf
from ..db import get_db
from ..errors import ConflictError, DomainError, NotFoundError
from ..models import (
    Household,
    HouseholdMealGroupAssignment,
    HouseholdMember,
    MealAllocation,
    MealType,
    Restriction,
    TargetProfile,
    UserRole,
)
from ..schemas import (
    MealGroupDefaultsOut,
    MealGroupDefaultsUpdate,
    MemberCreate,
    MemberOut,
    MemberUpdate,
    RestrictionIn,
    TargetProfileIn,
    TargetProfileOut,
)

router = APIRouter(tags=["household"])


def _meal_group_defaults(db: Session, household: Household) -> MealGroupDefaultsOut:
    members = list(
        db.scalars(
            select(HouseholdMember)
            .where(
                HouseholdMember.household_id == household.id,
                HouseholdMember.active.is_(True),
            )
            .order_by(HouseholdMember.name, HouseholdMember.id)
        ).all()
    )
    active_ids = {member.id for member in members}
    assignments = list(
        db.scalars(
            select(HouseholdMealGroupAssignment).where(
                HouseholdMealGroupAssignment.household_id == household.id,
                HouseholdMealGroupAssignment.member_id.in_(active_ids),
            )
        ).all()
    ) if active_ids else []
    result: dict[str, list[dict]] = {}
    for meal_type in MealType:
        groups: dict[str, list[str]] = {}
        assigned: set[str] = set()
        for assignment in assignments:
            if assignment.meal_type != meal_type.value:
                continue
            groups.setdefault(assignment.group_key, []).append(assignment.member_id)
            assigned.add(assignment.member_id)
        fallback = (
            sorted(groups, key=lambda key: (-len(groups[key]), key))[0]
            if groups
            else f"{meal_type.value}-shared"
        )
        groups.setdefault(fallback, [])
        groups[fallback].extend(member.id for member in members if member.id not in assigned)
        result[meal_type.value] = [
            {"group_key": key, "member_ids": sorted(member_ids)}
            for key, member_ids in sorted(
                groups.items(),
                key=lambda item: (
                    min(
                        (
                            next(member.name.casefold() for member in members if member.id == member_id)
                            for member_id in item[1]
                        ),
                        default="",
                    ),
                    item[0],
                ),
            )
            if member_ids
        ]
    return MealGroupDefaultsOut.model_validate(
        {"household_version": household.version, "groups": result}
    )


@router.get("/households/current")
def current_household(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    household = db.get(Household, context.user.household_id)
    return {"id": household.id, "name": household.name, "timezone": household.timezone, "version": household.version}


@router.get(
    "/households/current/meal-group-defaults",
    response_model=MealGroupDefaultsOut,
)
def get_meal_group_defaults(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
):
    household = db.get(Household, context.user.household_id)
    return _meal_group_defaults(db, household)


@router.put(
    "/households/current/meal-group-defaults",
    response_model=MealGroupDefaultsOut,
)
def update_meal_group_defaults(
    payload: MealGroupDefaultsUpdate,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if context.user.role != UserRole.OWNER.value:
        raise DomainError(
            "OWNER_REQUIRED", "Only the owner can change household meal groups", 403
        )
    household = db.scalar(
        select(Household)
        .where(Household.id == context.user.household_id)
        .with_for_update()
    )
    if household.version != payload.expected_version:
        raise ConflictError(
            "Household settings changed while you were editing them. Reload and try again."
        )
    active_ids = set(
        db.scalars(
            select(HouseholdMember.id).where(
                HouseholdMember.household_id == household.id,
                HouseholdMember.active.is_(True),
            )
        ).all()
    )
    for meal_type, groups in payload.groups.items():
        supplied = {member_id for group in groups for member_id in group.member_ids}
        if supplied != active_ids:
            raise DomainError(
                "INVALID_MEAL_GROUP_DEFAULTS",
                f"{meal_type.value.capitalize()} groups must include every active household member exactly once",
                422,
            )
    if active_ids:
        db.execute(
            delete(HouseholdMealGroupAssignment).where(
                HouseholdMealGroupAssignment.household_id == household.id,
                HouseholdMealGroupAssignment.member_id.in_(active_ids),
            )
        )
    for meal_type, groups in payload.groups.items():
        for group in groups:
            for member_id in group.member_ids:
                db.add(
                    HouseholdMealGroupAssignment(
                        household_id=household.id,
                        member_id=member_id,
                        meal_type=meal_type.value,
                        group_key=group.group_key,
                    )
                )
    household.version += 1
    db.commit()
    db.refresh(household)
    return _meal_group_defaults(db, household)


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
    db.flush()
    for meal_type in MealType:
        existing = list(
            db.scalars(
                select(HouseholdMealGroupAssignment).where(
                    HouseholdMealGroupAssignment.household_id == context.user.household_id,
                    HouseholdMealGroupAssignment.meal_type == meal_type.value,
                )
            ).all()
        )
        counts: dict[str, int] = {}
        for assignment in existing:
            counts[assignment.group_key] = counts.get(assignment.group_key, 0) + 1
        group_key = (
            sorted(counts, key=lambda key: (-counts[key], key))[0]
            if counts
            else f"{meal_type.value}-shared"
        )
        db.add(
            HouseholdMealGroupAssignment(
                household_id=context.user.household_id,
                member_id=member.id,
                meal_type=meal_type.value,
                group_key=group_key,
            )
        )
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


@router.get("/household-members/targets", response_model=list[TargetProfileOut])
def list_targets(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    targets = db.scalars(
        select(TargetProfile)
        .join(HouseholdMember, HouseholdMember.id == TargetProfile.member_id)
        .where(HouseholdMember.household_id == context.user.household_id)
        .order_by(HouseholdMember.name)
    ).all()
    return [_target_out(db, target) for target in targets]


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


@router.delete("/household-members/{member_id}/restrictions/{restriction_id}", status_code=204)
def delete_restriction(
    member_id: str,
    restriction_id: str,
    context: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    member = db.get(HouseholdMember, member_id)
    if member is None or member.household_id != context.user.household_id:
        raise NotFoundError("Household member")
    if context.user.role != UserRole.OWNER.value and context.user.member_id != member.id:
        raise DomainError("MEMBER_EDIT_FORBIDDEN", "You may edit only your linked profile", 403)
    restriction = db.get(Restriction, restriction_id)
    if restriction is None or restriction.member_id != member.id:
        raise NotFoundError("Restriction")
    db.delete(restriction)
    db.commit()
