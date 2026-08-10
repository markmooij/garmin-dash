"""Garmin authentication setup script."""

import os
import sys
from pathlib import Path

from garth.auth_tokens import OAuth2Token
from garth.http import Client


def setup():
    """Setup Garmin authentication (MFA + token cache)."""
    print("🔐 Garmin Authentication Setup")
    print("=" * 40)
    print()
    print("Step 1: Open https://connect.garmin.com/oauth_start in your browser")
    print("Step 2: Log in and grant permissions")
    print("Step 3: Copy the verification code from the browser")
    print()
    print("Press Enter when you have the verification code...")
    input()

    mfa_code = input("Enter verification code: ").strip()
    if not mfa_code:
        print("❌ Verification code is required.")
        return

    try:
        # Create OAuth2 token
        token = OAuth2Token(
            access_token=None,
            refresh_token=None,
            expires_in=0,
            expires_at=None,
        )
        
        # Login with MFA
        client = Client()
        client.login(mfa_code=mfa_code)
        
        # Save token to cache
        client.save(token_store="data/garmin/garmin_tokens.json")
        
        print()
        print("✅ Authentication successful!")
        print("📁 Tokens saved to: data/garmin/garmin_tokens.json")
        print()
        print("Next: Run 'gdash auth' to test the connection.")
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        return


if __name__ == "__main__":
    setup()
