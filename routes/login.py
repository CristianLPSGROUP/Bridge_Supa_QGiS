from supabase_auth.errors import AuthApiError
from .utils.limiter import limiter
from .utils.supabase_manager import supabase_client
import asyncio
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/auth", tags=["Auth"])


### Models
class ProjectItem(BaseModel):
    project_id: int
    project_name: str


class Credentials(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    message: str
    user_id: str
    projects: list[ProjectItem]


### Routes
@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(request: Request, creds: Credentials, response: Response):
    try:
        print(f"Login attempt for email: {creds.email}")

        auth_response = await asyncio.to_thread(
            supabase_client.auth.sign_in_with_password,
            {
                "email": creds.email,
                "password": creds.password,
            },
        )

        response.set_cookie(
            key="access_token",
            value=auth_response.session.access_token,
            httponly=True,
            secure=True,  # Only over HTTPS in production
            samesite="lax",
            max_age=auth_response.session.expires_in,
        )
        response.set_cookie(
            key="refresh_token",
            value=auth_response.session.refresh_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_response.session.expires_in,
        )
        user_id = str(auth_response.user.id)
        # 🔹 RPC: proyectos del usuario
        projects_response = await asyncio.to_thread(
            lambda: supabase_client.rpc(
                "get_projects_by_user", {"p_user_id": user_id}
            ).execute()
        )
        print("Raw projects_response:", projects_response.data)

        projects = projects_response.data or []
        projects = [
            {"project_id": p["project_id"], "project_name": p["project_name"]}
            for p in projects
        ]

        print(f"Login successful for user: {auth_response.user.id}")
        return LoginResponse(
            message="Login successful",
            user_id=str(auth_response.user.id),
            projects=projects,
        )
    except AuthApiError as e:
        print(f"AuthApiError: {e}")
        raise HTTPException(status_code=401, detail="User or Password are incorrect")
    except Exception as e:
        import traceback

        print(f"Login error: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail="Authentication failed, try again later"
        )


@router.post("/logout")
@limiter.limit("5/minute")
async def logout(request: Request, response: Response):
    try:
        await asyncio.to_thread(supabase_client.auth.sign_out)
        response.delete_cookie(
            key="access_token", httponly=True, secure=True, samesite="lax"
        )
        response.delete_cookie(
            key="refresh_token", httponly=True, secure=True, samesite="lax"
        )
        return {"message": "Logged out"}
    except Exception:
        raise HTTPException(status_code=500, detail="Logout failed")


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh(request: Request, response: Response):
    try:
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            raise HTTPException(status_code=401, detail="No refresh token")

        auth_response = await asyncio.to_thread(
            supabase_client.auth.refresh_session, refresh_token
        )

        response.set_cookie(
            key="access_token",
            value=auth_response.session.access_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_response.session.expires_in,
        )
        response.set_cookie(
            key="refresh_token",
            value=auth_response.session.refresh_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_response.session.expires_in,
        )

        return {"message": "Token refreshed"}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token refresh failed")
