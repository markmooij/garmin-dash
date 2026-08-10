"""CLI for Garmin authentication.

Commands:
    gdash auth status          Show whether cached tokens work
    gdash auth start           Begin login (prompts for MFA if required)
    gdash auth code <CODE>     Finish an MFA login with the emailed code
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from .session import (
    AuthError,
    TOKEN_DIR,
    finish_login,
    resume_from_tokens,
    start_login,
    whoami,
)


def cmd_status() -> int:
    """Report whether cached tokens are usable."""
    client = resume_from_tokens()
    if client is None:
        print("❌ Not authenticated (no usable tokens).")
        print("   Run: gdash auth start")
        return 1
    print(f"✅ Authenticated as: {whoami(client)}")
    print(f"📁 Tokens: {TOKEN_DIR}")
    return 0


def cmd_start() -> int:
    """Start login; prompt for the MFA code if Garmin asks for one."""
    client = resume_from_tokens()
    if client is not None:
        print(f"✅ Already authenticated as: {whoami(client)}")
        return 0

    state, client = start_login()

    if state == "authenticated":
        print(f"✅ Authenticated as: {whoami(client)}")
        print(f"📁 Tokens saved to: {TOKEN_DIR}")
        return 0

    print("📧 Garmin sent an MFA code to your email/phone.")
    print()
    try:
        code = input("Enter MFA code: ").strip()
    except EOFError:
        print("No TTY available. Run instead:")
        print("   gdash auth code <CODE>")
        return 2

    client = finish_login(code)
    print(f"✅ Authenticated as: {whoami(client)}")
    print(f"📁 Tokens saved to: {TOKEN_DIR}")
    return 0


def cmd_code(code: str) -> int:
    """Finish a pending MFA login non-interactively."""
    client = finish_login(code)
    print(f"✅ Authenticated as: {whoami(client)}")
    print(f"📁 Tokens saved to: {TOKEN_DIR}")
    return 0


def main() -> int:
    """CLI entry point."""
    load_dotenv()

    args = sys.argv[1:]
    cmd = args[0] if args else "status"

    try:
        if cmd == "status":
            return cmd_status()
        if cmd == "start":
            return cmd_start()
        if cmd == "code":
            if len(args) < 2:
                print("Usage: gdash auth code <MFA_CODE>")
                return 2
            return cmd_code(args[1])
        print(f"Unknown command: {cmd}")
        print("Usage: gdash auth [status|start|code <CODE>]")
        return 2
    except AuthError as e:
        print(f"❌ {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ Login failed: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
