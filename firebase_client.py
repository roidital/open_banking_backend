"""
Firebase client for interacting with Firebase Auth and Realtime Database.
Supports multiple bank/card accounts per user.
"""
import firebase_admin
from firebase_admin import credentials, db, auth
from config import Config
from datetime import datetime
import logging
import hashlib

logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK
_initialized = False

def init_firebase():
    """Initialize Firebase Admin SDK."""
    global _initialized
    if _initialized:
        return
    
    try:
        creds_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
        if creds_json:
            creds_dict = json.loads(creds_json)
            cred = credentials.Certificate(creds_dict)
        
        firebase_admin.initialize_app(cred, {
            'databaseURL': Config.FIREBASE_DATABASE_URL
        })
        _initialized = True
        logger.info("Firebase initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        raise


def verify_firebase_token(id_token: str) -> dict:
    """
    Verify a Firebase ID token and return the decoded token.
    
    Args:
        id_token: Firebase ID token from the client
        
    Returns:
        Decoded token containing user info (uid, email, etc.)
        
    Raises:
        ValueError: If token is invalid
    """
    init_firebase()
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise ValueError(f"Invalid Firebase token: {e}")


def save_user_credentials(user_id: str, company_id: str, encrypted_credentials: dict):
    """
    Save encrypted credentials for a user's bank/card account to Firebase.
    Supports multiple accounts per user by storing under user_id/company_id.
    
    Args:
        user_id: Firebase user ID
        company_id: Bank/card company identifier
        encrypted_credentials: Dictionary with encrypted_data and nonce
    """
    init_firebase()
    # Store credentials under user_id/company_id to support multiple accounts
    ref = db.reference(f'user_credentials/{user_id}/{company_id}')
    ref.set({
        'credentials': encrypted_credentials,
        'scraping_enabled': True,
        'created_at': datetime.utcnow().isoformat(),
        'last_scraped': None
    })
    logger.info(f"Saved credentials for user {user_id}, company {company_id}")


def get_user_credentials(user_id: str, company_id: str = None) -> dict:
    """
    Get stored credentials for a user.
    
    Args:
        user_id: Firebase user ID
        company_id: Optional - if provided, returns only that company's credentials
        
    Returns:
        User credentials data or None if not found
        If company_id is None, returns all accounts for the user
    """
    init_firebase()
    if company_id:
        ref = db.reference(f'user_credentials/{user_id}/{company_id}')
        data = ref.get()
        if data:
            data['company_id'] = company_id
        return data
    else:
        ref = db.reference(f'user_credentials/{user_id}')
        return ref.get()


def get_user_connected_accounts(user_id: str) -> list:
    """
    Get list of connected accounts (company IDs) for a user.
    
    Args:
        user_id: Firebase user ID
        
    Returns:
        List of company IDs that the user has connected
    """
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}')
    data = ref.get() or {}
    
    # Only include entries that are proper account objects (dict with 'credentials')
    return [key for key, value in data.items() 
            if isinstance(value, dict) and 'credentials' in value]


def get_all_enabled_accounts() -> list:
    """
    Get all user accounts with scraping enabled.
    
    Returns:
        List of (user_id, company_id, account_data) tuples
    """
    init_firebase()
    ref = db.reference('user_credentials')
    all_users = ref.get() or {}
    
    enabled_accounts = []
    for user_id, companies in all_users.items():
        if isinstance(companies, dict):
            for company_id, account_data in companies.items():
                # Only include proper account entries (dict with credentials)
                if isinstance(account_data, dict) and 'credentials' in account_data:
                    if account_data.get('scraping_enabled', False):
                        enabled_accounts.append((user_id, company_id, account_data))
    
    return enabled_accounts


def update_last_scraped(user_id: str, company_id: str):
    """Update the last_scraped timestamp for a specific account."""
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}/{company_id}/last_scraped')
    ref.set(datetime.utcnow().isoformat())


def delete_user_credentials(user_id: str, company_id: str = None):
    """
    Delete stored credentials for a user.
    
    Args:
        user_id: Firebase user ID
        company_id: Optional - if provided, deletes only that company's credentials
                   If None, deletes ALL credentials for the user
    """
    init_firebase()
    if company_id:
        ref = db.reference(f'user_credentials/{user_id}/{company_id}')
        ref.delete()
        logger.info(f"Deleted credentials for user {user_id}, company {company_id}")
    else:
        ref = db.reference(f'user_credentials/{user_id}')
        ref.delete()
        logger.info(f"Deleted all credentials for user {user_id}")


def generate_transaction_id(txn: dict) -> str:
    """
    Generate a unique ID for a transaction to detect duplicates.
    
    Args:
        txn: Transaction dictionary with date, description, amount
        
    Returns:
        Unique hash string for the transaction
    """
    # Create a unique key from transaction details
    key_parts = [
        str(txn.get('date', '')),
        str(txn.get('description', '')),
        str(txn.get('chargedAmount', txn.get('originalAmount', ''))),
        str(txn.get('identifier', ''))  # Some scrapers provide unique identifiers
    ]
    key_string = '|'.join(key_parts)
    return hashlib.md5(key_string.encode()).hexdigest()


def save_scraped_expenses(user_id: str, company_id: str, expenses_data: dict):
    """
    Save scraped expenses to Firebase for the app to read.
    Merges new transactions with existing ones to avoid duplicates.
    
    Args:
        user_id: Firebase user ID
        company_id: Bank/card company identifier
        expenses_data: Scraped expenses data from the scraper service
    """
    init_firebase()
    
    # Get existing expenses for this user
    ref = db.reference(f'scraped_expenses/{user_id}')
    existing_data = ref.get() or {}
    
    # Get existing transactions (keyed by transaction ID for dedup)
    existing_txns = existing_data.get('transactions', {})
    
    # Process new transactions from all accounts in the scraped data
    new_txn_count = 0
    accounts = expenses_data.get('accounts', [])
    
    for account in accounts:
        account_number = account.get('accountNumber', 'unknown')
        txns = account.get('txns', [])
        
        for txn in txns:
            # Add source info to transaction
            txn['source_company'] = company_id
            txn['source_account'] = account_number
            
            # Generate unique ID for deduplication
            txn_id = generate_transaction_id(txn)
            
            # Only add if not already exists
            if txn_id not in existing_txns:
                existing_txns[txn_id] = txn
                new_txn_count += 1
    
    # Update the database with merged transactions
    ref.set({
        'last_updated': datetime.utcnow().isoformat(),
        'transactions': existing_txns,
        # Keep a summary of connected accounts
        'connected_accounts': get_user_connected_accounts(user_id)
    })
    
    logger.info(f"Saved {new_txn_count} new transactions for user {user_id} from {company_id}")
    return new_txn_count


def update_scraper_status(user_id: str, status: str, error_message: str = None, company_id: str = None):
    """
    Update the scraper status for a user.
    
    Args:
        user_id: Firebase user ID
        status: 'success', 'error', or 'pending'
        error_message: Optional error message if status is 'error'
        company_id: Optional company ID for account-specific status
    """
    init_firebase()
    
    # Update overall user status
    ref = db.reference(f'scraper_status/{user_id}')
    current_status = ref.get() or {}
    
    # Update account-specific status if company_id provided
    account_statuses = current_status.get('accounts', {})
    if company_id:
        account_statuses[company_id] = {
            'status': status,
            'last_run': datetime.utcnow().isoformat(),
            'error_message': error_message
        }
    
    # Determine overall status (error if any account has error)
    overall_status = status
    if account_statuses:
        has_error = any(acc.get('status') == 'error' for acc in account_statuses.values())
        has_pending = any(acc.get('status') == 'pending' for acc in account_statuses.values())
        if has_error:
            overall_status = 'error'
        elif has_pending:
            overall_status = 'pending'
        else:
            overall_status = 'success'
    
    ref.set({
        'status': overall_status,
        'last_run': datetime.utcnow().isoformat(),
        'error_message': error_message if overall_status == 'error' else None,
        'has_credentials': True,
        'accounts': account_statuses,
        'connected_accounts': get_user_connected_accounts(user_id)
    })
