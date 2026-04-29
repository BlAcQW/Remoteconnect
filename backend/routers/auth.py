import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..database import get_db
from ..limiting import limiter
from ..models.user import User

router = APIRouter()
security = HTTPBearer()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET environment variable must be set")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 hours


class UserCreate(BaseModel):
    """Public self-service registration. Always creates a `technician` user.

    Admin accounts must be provisioned out-of-band via
    `backend/scripts/create_admin.py` — never via this endpoint.
    """

    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    role: str


@router.get("/me", response_model=MeResponse)
async def me(current: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=current.id, email=current.email, role=current.role)


def _new_access_token(email: str) -> Token:
    token = create_access_token(
        data={"sub": email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=token, token_type="bearer")


def _client_ip(req: Request) -> str | None:
    return req.client.host if req.client else None


@router.post("/register", response_model=Token)
async def register(
    user: UserCreate, request: Request, db: AsyncSession = Depends(get_db),
) -> Token:
    result = await db.execute(select(User).where(User.email == user.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    db_user = User(
        email=user.email,
        password_hash=get_password_hash(user.password),
        role="technician",  # locked — admins are created via the CLI only
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    await audit(
        db, "auth.register",
        user_id=db_user.id, actor_ip=_client_ip(request),
        detail={"email": user.email},
    )
    return _new_access_token(db_user.email)


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    user: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> Token:
    # `request` is required by slowapi's limiter (it inspects the client IP).
    result = await db.execute(select(User).where(User.email == user.email))
    db_user = result.scalar_one_or_none()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        await audit(
            db, "auth.login.failed",
            actor_ip=_client_ip(request),
            detail={"email": user.email, "reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await audit(
        db, "auth.login.ok",
        user_id=db_user.id, actor_ip=_client_ip(request),
    )
    return _new_access_token(db_user.email)
