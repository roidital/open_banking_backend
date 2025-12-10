# Firebase Realtime Database Structure

This document describes the Firebase Realtime Database structure used by the Scraper Entry Point service.

## Database Nodes

### 1. `/user_credentials/{userId}`

**Purpose**: Store encrypted bank credentials for each user.

**Access**: 
- Read/Write: Only by Admin SDK (server-side)
- Users cannot read/write directly

**Structure**:
```json
{
  "company_id": "hapoalim",
  "credentials": {
    "encrypted_data": "base64-encoded-ciphertext",
    "nonce": "base64-encoded-nonce"
  },
  "scraping_enabled": true,
  "created_at": "2025-12-09T10:00:00Z",
  "last_scraped": "2025-12-09T06:00:00Z"
}
```

### 2. `/scraped_expenses/{userId}`

**Purpose**: Store scraped expense data for the app to read.

**Access**:
- Read: User can read their own data
- Write: Only by Admin SDK (server-side)

**Structure**:
```json
{
  "last_updated": "2025-12-09T06:00:00Z",
  "data": {
    "success": true,
    "accounts": [
      {
        "accountNumber": "****1234",
        "txns": [
          {
            "date": "2025-12-08",
            "description": "Supermarket ABC",
            "originalAmount": -150.00,
            "originalCurrency": "ILS",
            "chargedAmount": -150.00,
            "type": "normal",
            "status": "completed",
            "identifier": "txn-12345",
            "category": "groceries"
          }
        ]
      }
    ]
  }
}
```

### 3. `/scraper_status/{userId}`

**Purpose**: Track scraping status for UI feedback in the app.

**Access**:
- Read: User can read their own status
- Write: Only by Admin SDK (server-side)

**Structure**:
```json
{
  "status": "success",
  "last_run": "2025-12-09T06:00:00Z",
  "error_message": null,
  "has_credentials": true
}
```

**Status values**:
- `pending`: Scrape is in progress
- `success`: Last scrape completed successfully
- `error`: Last scrape failed (see error_message)
- `deleted`: User deleted their credentials

### 4. `/shared_preferences/{userId}` (Existing)

**Purpose**: Existing node for app preferences sync.

**Access**:
- Read/Write: User can access their own data

## Security Rules

The security rules (`firebase-database-rules.json`) ensure:

1. Users can only read their own scraped expenses and status
2. Users cannot directly read or write credentials (server-only)
3. Only authenticated users can access their data

## Setting Up Rules

Deploy the rules to Firebase:

```bash
firebase deploy --only database
```

Or manually copy the rules from `firebase-database-rules.json` to the Firebase Console:
1. Go to Firebase Console → Realtime Database → Rules
2. Replace existing rules with the content of `firebase-database-rules.json`
3. Click "Publish"

