# Firebase Realtime Database Structure

This document describes the Firebase Realtime Database structure used by the Scraper Entry Point service.
**Updated to support multiple bank/card accounts per user.**

## Database Nodes

### 1. `/user_credentials/{userId}/{companyId}`

**Purpose**: Store encrypted bank credentials for each user's account.
Supports multiple accounts per user by storing under `{userId}/{companyId}`.

**Access**: 
- Read/Write: Only by Admin SDK (server-side)
- Users cannot read/write directly

**Structure**:
```json
{
  "credentials": {
    "encrypted_data": "base64-encoded-ciphertext",
    "nonce": "base64-encoded-nonce"
  },
  "scraping_enabled": true,
  "created_at": "2025-12-09T10:00:00Z",
  "last_scraped": "2025-12-09T06:00:00Z"
}
```

**Example** (user with two accounts):
```json
{
  "user_credentials": {
    "user123": {
      "hapoalim": {
        "credentials": { ... },
        "scraping_enabled": true,
        "last_scraped": "2025-12-09T06:00:00Z"
      },
      "isracard": {
        "credentials": { ... },
        "scraping_enabled": true,
        "last_scraped": "2025-12-09T06:00:00Z"
      }
    }
  }
}
```

### 2. `/scraped_expenses/{userId}`

**Purpose**: Store scraped expense transactions for the app to read.
Transactions are stored in a flat dictionary keyed by unique transaction ID to enable deduplication.

**Access**:
- Read: User can read their own data
- Write: Only by Admin SDK (server-side)

**Structure**:
```json
{
  "last_updated": "2025-12-09T06:00:00Z",
  "connected_accounts": ["hapoalim", "isracard"],
  "transactions": {
    "abc123hash": {
      "date": "2025-12-08",
      "description": "Supermarket ABC",
      "originalAmount": -150.00,
      "chargedAmount": -150.00,
      "originalCurrency": "ILS",
      "type": "normal",
      "status": "completed",
      "source_company": "hapoalim",
      "source_account": "****1234",
      "category": "groceries"
    },
    "def456hash": {
      "date": "2025-12-07",
      "description": "Gas Station",
      "chargedAmount": -200.00,
      "source_company": "isracard",
      "source_account": "****5678"
    }
  }
}
```

**Key features**:
- Transactions from ALL connected accounts are stored together
- Each transaction has `source_company` and `source_account` to identify origin
- Transaction IDs are hashes of (date + description + amount) for deduplication
- New scrapes merge with existing transactions, never overwrite

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
  "has_credentials": true,
  "connected_accounts": ["hapoalim", "isracard"],
  "accounts": {
    "hapoalim": {
      "status": "success",
      "last_run": "2025-12-09T06:00:00Z",
      "error_message": null
    },
    "isracard": {
      "status": "error",
      "last_run": "2025-12-09T06:00:00Z",
      "error_message": "Invalid credentials"
    }
  }
}
```

**Status values**:
- `pending`: Scrape is in progress
- `success`: Last scrape completed successfully
- `error`: Last scrape failed (see error_message)
- `deleted`: User deleted their credentials

**Note**: Overall status reflects the worst status among all accounts (error > pending > success)

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

## Migration Notes

If you have existing data in the old format (`/user_credentials/{userId}` with single credentials object),
the app includes backwards compatibility handling. However, new accounts will use the new structure.
