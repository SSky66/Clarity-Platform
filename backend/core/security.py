from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
import jwt

SECRET_KEY = "clarity-dev-key-change-before-deploy"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
