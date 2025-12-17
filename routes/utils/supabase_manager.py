from supabase import create_client, Client
import os
from dotenv import load_dotenv
from fastapi import HTTPException, Cookie
from typing import Annotated
import jwt

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")

supabase_client: Client = create_client(
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
)

async def get_authenticated_supabase_client(
    access_token: Annotated[str | None, Cookie()] = None,
    refresh_token: Annotated[str | None, Cookie()] = None
) -> tuple[Client, str]:
    print(f"Auth check - access_token present: {bool(access_token)}, refresh_token present: {bool(refresh_token)}")

    if not access_token:
        print("No access token in cookies")
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(access_token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id:
            print("No user_id in token payload")
            raise HTTPException(status_code=401, detail="Invalid token")
        print(f"Successfully authenticated user: {user_id}")
    except jwt.DecodeError as e:
        print(f"JWT decode error: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.set_session(access_token, refresh_token)
    return client, user_id