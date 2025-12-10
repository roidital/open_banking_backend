"""
Firebase client for interacting with Firebase Auth and Realtime Database.
"""
import firebase_admin
from firebase_admin import credentials, db, auth
from config import Config
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Initialize Firebase Admin SDK
_initialized = False

def init_firebase():
    """Initialize Firebase Admin SDK."""
    global _initialized
    if _initialized:
        return
    
    try:
        cred = credentials.Certificate(Config.FIREBASE_CREDENTIALS_PATH)
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
    Save encrypted credentials for a user to Firebase.
    
    Args:
        user_id: Firebase user ID
        company_id: Bank/card company identifier
        encrypted_credentials: Dictionary with encrypted_data and nonce
    """
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}')
    ref.set({
        'company_id': company_id,
        'credentials': encrypted_credentials,
        'scraping_enabled': True,
        'created_at': datetime.utcnow().isoformat(),
        'last_scraped': None
    })
    logger.info(f"Saved credentials for user {user_id}")


def get_user_credentials(user_id: str) -> dict:
    """
    Get stored credentials for a user.
    
    Args:
        user_id: Firebase user ID
        
    Returns:
        User credentials data or None if not found
    """
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}')
    return ref.get()


def get_all_enabled_users() -> list:
    """
    Get all users with scraping enabled.
    
    Returns:
        List of (user_id, credentials_data) tuples
    """
    init_firebase()
    ref = db.reference('user_credentials')
    all_users = ref.get() or {}
    
    enabled_users = []
    for user_id, data in all_users.items():
        if data.get('scraping_enabled', False):
            enabled_users.append((user_id, data))
    
    return enabled_users


def update_last_scraped(user_id: str):
    """Update the last_scraped timestamp for a user."""
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}/last_scraped')
    ref.set(datetime.utcnow().isoformat())


def delete_user_credentials(user_id: str):
    """Delete stored credentials for a user."""
    init_firebase()
    ref = db.reference(f'user_credentials/{user_id}')
    ref.delete()
    logger.info(f"Deleted credentials for user {user_id}")


def save_scraped_expenses(user_id: str, expenses_data: dict):
    """
    Save scraped expenses to Firebase for the app to read.
    
    Args:
        user_id: Firebase user ID
        expenses_data: Scraped expenses data from the scraper service
    """
    init_firebase()
    ref = db.reference(f'scraped_expenses/{user_id}')
    ref.set({
        'last_updated': datetime.utcnow().isoformat(),
        'data': expenses_data
    })
    logger.info(f"Saved scraped expenses for user {user_id}")


def update_scraper_status(user_id: str, status: str, error_message: str = None):
    """
    Update the scraper status for a user.
    
    Args:
        user_id: Firebase user ID
        status: 'success', 'error', or 'pending'
        error_message: Optional error message if status is 'error'
    """
    init_firebase()
    ref = db.reference(f'scraper_status/{user_id}')
    ref.set({
        'status': status,
        'last_run': datetime.utcnow().isoformat(),
        'error_message': error_message,
        'has_credentials': True
    })

