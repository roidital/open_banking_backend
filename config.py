import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Firebase settings
    FIREBASE_DATABASE_URL = os.environ.get('FIREBASE_DATABASE_URL', 'https://roidbudgetapp-default-rtdb.firebaseio.com')
    FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', 'firebase-credentials.json')
    
    # Scraper service URL (your existing bank-scraper-service)
    SCRAPER_SERVICE_URL = os.environ.get('SCRAPER_SERVICE_URL', 'https://your-scraper-service.com')
    
    # Encryption key for credentials (32 bytes for AES-256)
    # In production, this should come from a secure secret manager
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
    
    # Scheduler secret for authenticating scheduled job requests
    SCHEDULER_SECRET = os.environ.get('SCHEDULER_SECRET', 'scheduler-secret-change-in-production')

