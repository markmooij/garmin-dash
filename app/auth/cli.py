"""CLI for Garmin authentication (MFA + token cache)."""

import json
import os
import sys
from pathlib import Path
from typing import Optional

from garth import login
from garth.auth_tokens import OAuth2Token
from garth.http import Client


class AuthSettings:
    """Auth-specific settings."""

    TOKEN_CACHE_DIR: str = "data/garmin"
    TOKEN_CACHE_FILE: str = "garmin_tokens.json"

    @property
    def token_cache_path(self) -> Path:
        """Return the token cache file path."""
        return Path(self.TOKEN_CACHE_DIR) / self.TOKEN_CACHE_FILE


class GarminAuthCLI:
    """Garmin authentication CLI."""

    def __init__(self, settings: AuthSettings):
        self.settings = settings

    def setup(self):
        """Interactive MFA login and token cache setup."""
        print("🔐 Garmin Authentication Setup")
        print("=" * 40)
        print("This will guide you through MFA authentication.")
        print()
        print("Step 1: Open https://connect.garmin.com/oauth_start")
        print("Step 2: Log in and grant permissions")
        print("Step 3: Copy the verification code from the browser")
        print()

        # Wait for user to complete steps
        input("Press Enter when you have the verification code...")

        # Prompt for verification code
        mfa_code = input("Enter verification code: ").strip()
        if not mfa_code:
            print("❌ Verification code is required.")
            sys.exit(1)

        # Perform MFA login using garth
        try:
            # Create OAuth2 token
            token = OAuth2Token(
                access_token=None,  # Will be filled after login
                refresh_token=None,  # Will be filled after login
                expires_in=0,
                expires_at=None,
            )
            
            # Login with MFA
            client = Client()
            client.login(mfa_code=mfa_code)
            
            # Save token to cache
            client.save(token_store=self.settings.token_cache_path)
            
            print()
            print("✅ Authentication successful!")
            print(f"📁 Tokens saved to: {self.settings.token_cache_path}")
            print()
            print("Next: Run 'gdash auth' to test the connection.")
            
        except Exception as e:
            print(f"❌ Authentication failed: {e}")
            sys.exit(1)

    def login(self):
        """Test MFA login and save token cache."""
        print("🔐 Testing Garmin MFA Login")
        print("=" * 40)

        try:
            # Load existing token
            client = Client()
            client.load(token_store=self.settings.token_cache_path)
            
            # Check if token is valid
            if client.status_code == 200:
                print("✅ Token is valid!")
                print(f"📁 Token cache location: {self.settings.token_cache_path}")
                print()
                print("Next: Run 'gdash ingest-backfill' to sync your data.")
            else:
                print("❌ Token is invalid or expired. Run 'gdash auth setup' to re-authenticate.")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ Garth error: {e}")
            sys.exit(1)

    def interactive_login(self):
        """Interactive MFA login flow."""
        print("🔐 Garmin MFA Login")
        print("=" * 40)
        print("This will open a browser and guide you through MFA.")
        print()
        print("Step 1: Open https://connect.garmin.com/oauth_start in your browser")
        print("Step 2: Log in and grant permissions")
        print("Step 3: Copy the verification code from the browser")
        print()
        print("Press Enter when you're ready to enter the verification code...")
        input()

        mfa_code = input("Enter verification code: ").strip()
        if not mfa_code:
            print("❌ Verification code is required.")
            sys.exit(1)

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
            client.save(token_store=self.settings.token_cache_path)
            
            print()
            print("✅ Authentication successful!")
            print(f"📁 Tokens saved to: {self.settings.token_cache_path}")
            print()
            print("Next: Run 'gdash auth' to test the connection.")
            
        except Exception as e:
            print(f"❌ Garth error: {e}")
            sys.exit(1)


def main():
    """CLI main entry point."""
    settings = AuthSettings()
    cli = GarminAuthCLI(settings)

    # Parse arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "setup":
            cli.setup()
        elif arg == "test":
            cli.login()
        else:
            cli.interactive_login()
    else:
        cli.interactive_login()


if __name__ == "__main__":
    main()
