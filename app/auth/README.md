# Garmin Authentication Module

This module handles Garmin Connect authentication using the `garth` library.

## Setup

```bash
gdash auth setup
```

This will guide you through the MFA authentication process:
1. Open https://connect.garmin.com/oauth_start in your browser
2. Log in and grant permissions
3. Copy the verification code from the browser
4. Enter the verification code when prompted

## Testing

```bash
gdash auth test
```

This verifies that your token cache is valid and the connection is working.

## Token Cache

Tokens are stored in `data/garmin/garmin_tokens.json`. This file is gitignored and should never be committed.

## Notes

- The `garth` library is deprecated and no longer maintained (see https://github.com/matin/garth/discussions/222)
- We use it for now because it's the most actively maintained Garmin API client
- Future versions may migrate to an official Garmin API client
