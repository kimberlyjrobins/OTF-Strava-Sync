#!/usr/bin/env python3
"""
One-time helper to generate a Garmin Connect session token for use in GitHub Actions.

Run this ONCE on your own computer. It handles MFA interactively, then saves
the session to a string you can paste in as the GARMINTOKENS GitHub secret.
After that, the GitHub Actions workflow uses the token directly without MFA.

Usage:
    pip install garminconnect
    python get_garmin_session.py
"""

import getpass
import sys

try:
    from garminconnect import Garmin
except ImportError:
    print("Please install garminconnect first:\n  pip install garminconnect")
    sys.exit(1)


def main():
    print("\n=== Garmin Connect Session Generator ===\n")
    print("This runs once on your computer to generate a session token.")
    print("You'll paste that token into GitHub as the GARMINTOKENS secret.\n")

    email = input("Garmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password: ")

    client = Garmin(email, password)

    print("\nLogging in...")
    try:
        mfa_status, _ = client.login()
    except Exception as e:
        print(f"\nLogin failed: {e}")
        sys.exit(1)

    if mfa_status:
        print("\nGarmin is asking for a one-time MFA code.")
        print("Check your email or authenticator app for the code.\n")
        mfa_code = input("Enter MFA code: ").strip()
        try:
            client.resume_login(mfa_code)
        except Exception as e:
            print(f"\nMFA failed: {e}")
            sys.exit(1)

    # Serialize the session to a string
    token_str = client.client.dumps()

    print("\n" + "="*60)
    print("SUCCESS! Here is your GARMINTOKENS value:\n")
    print(token_str)
    print("\n" + "="*60)
    print("\nNext steps:")
    print("  1. Copy the entire token string above (everything between the lines)")
    print("  2. In your GitHub repo: Settings → Secrets and variables → Actions")
    print("  3. Create a new secret named:  GARMINTOKENS")
    print("  4. Paste the token string as the value")
    print("\nThe token is long-lived but will eventually expire.")
    print("If the sync starts failing with auth errors, just re-run this script.\n")


if __name__ == "__main__":
    main()
