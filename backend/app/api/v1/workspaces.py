from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.entities import User, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas.workspaces import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.core.audit import record_audit

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

RANK = {"VIEWER": 1, "EDITOR": 2, "ADMIN": 3, "OWNER": 4}


def membership(db: Session, workspace_id: UUID, user_id: UUID) -> WorkspaceMember:
    item = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return item


def require_role(db: Session, workspace_id: UUID, user: User, minimum: WorkspaceRole) -> WorkspaceMember:
    member = membership(db, workspace_id, user.id)
    if RANK[member.role.value] < RANK[minimum.value]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions")
    return member


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workspace:
    if db.query(Workspace).filter(Workspace.slug == payload.slug).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A workspace with this slug already exists")

    workspace = Workspace(name=payload.name.strip(), slug=payload.slug, description=payload.description, owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER))
    record_audit(db, workspace.id, user.id, "WORKSPACE_CREATED", "workspace", workspace.id)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Workspace]:
    ids = db.query(WorkspaceMember.workspace_id).filter(WorkspaceMember.user_id == user.id)
    return db.query(Workspace).filter(Workspace.id.in_(ids)).order_by(Workspace.created_at.desc()).all()


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workspace:
    membership(db, workspace_id, user.id)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workspace:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    changes = payload.model_dump(exclude_unset=True)
    if "slug" in changes and db.query(Workspace).filter(Workspace.slug == changes["slug"], Workspace.id != workspace_id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A workspace with this slug already exists")
    for key, value in changes.items():
        setattr(workspace, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    member = require_role(db, workspace_id, user, WorkspaceRole.OWNER)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.owner_id == user.id).first()
    if not workspace or member.role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the workspace owner can delete it")
    db.delete(workspace)
    db.commit()


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
def list_members(
    workspace_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceMember]:
    membership(db, workspace_id, user.id)
    return db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).all()


@router.post("/{workspace_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(
    workspace_id: UUID,
    payload: MemberCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceMember:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    if payload.role == "OWNER":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ownership cannot be assigned")
    target = db.query(User).filter(User.email == payload.email.lower()).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == target.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a workspace member")

    member = WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole(payload.role))
    db.add(member)
    record_audit(db, workspace_id, user.id, "WORKSPACE_MEMBER_ADDED", "workspace_member", target.id)
    db.commit()
    db.refresh(member)
    return member


@router.patch("/{workspace_id}/members/{member_id}", response_model=MemberResponse)
def change_member_role(
    workspace_id: UUID,
    member_id: UUID,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceMember:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    target = db.query(WorkspaceMember).filter(WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if target.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace ownership cannot be changed")
    if payload.role == "OWNER":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ownership cannot be assigned")
    target.role = WorkspaceRole(payload.role)
    record_audit(db, workspace_id, user.id, "WORKSPACE_MEMBER_ROLE_CHANGED", "workspace_member", target.id, {"role": payload.role})
    db.commit()
    db.refresh(target)
    return target


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: UUID,
    member_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_role(db, workspace_id, user, WorkspaceRole.ADMIN)
    target = db.query(WorkspaceMember).filter(WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if target.role == WorkspaceRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The workspace owner cannot be removed")
    db.delete(target)
    record_audit(db, workspace_id, user.id, "WORKSPACE_MEMBER_REMOVED", "workspace_member", target.id)
    db.commit()
