"""
Scraper Entry Point Service - Flask Application

This service provides a web interface for users to enter their bank credentials,
stores them securely, and orchestrates scraping jobs with the existing bank-scraper-service.
Supports multiple bank/card accounts per user.
"""
import os
import logging
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect
from flask_cors import CORS
from config import Config
from encryption import encrypt_credentials, decrypt_credentials
from firebase_client import (
    verify_firebase_token,
    save_user_credentials,
    get_user_credentials,
    get_user_connected_accounts,
    get_all_enabled_accounts,
    update_last_scraped,
    delete_user_credentials,
    save_scraped_expenses,
    update_scraper_status
)

# Configure logging - scrub sensitive data
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# Bank/card credential field configurations
CREDENTIAL_FIELDS = {
    'leumi': ['username', 'password'],
    'mizrahi': ['username', 'password'],
    'otsarHahayal': ['username', 'password'],
    'max': ['username', 'password'],
    'visaCal': ['username', 'password'],
    'union': ['username', 'password'],
    'beinleumi': ['username', 'password'],
    'massad': ['username', 'password'],
    'pagi': ['username', 'password'],
    'hapoalim': ['userCode', 'password'],
    'discount': ['id', 'password', 'num'],
    'mercantile': ['id', 'password', 'num'],
    'isracard': ['id', 'password', 'card6Digits'],
    'amex': ['id', 'password', 'card6Digits'],
    'yahav': ['username', 'password'],  # TODO: add nationalID
    'beyahadBishvilha': ['id', 'password'],
    'behatsdaa': ['id', 'password'],
}

COMPANY_DISPLAY_NAMES = {
    'visaCal': 'Visa Cal',
    'isracard': 'Isracard',
    'amex': 'American Express',
    'hapoalim': 'Bank Hapoalim',
    'leumi': 'Bank Leumi',
    'max': 'Max',
    'mizrahi': 'Mizrahi Tefahot',
    'otsarHahayal': 'Otsar Hahayal',
    'union': 'Union Bank',
    'beinleumi': 'First International',
    'massad': 'Massad',
    'pagi': 'Bank Pagi',
    'discount': 'Discount Bank',
    'mercantile': 'Mercantile Discount',
    'yahav': 'Bank Yahav',
    'beyahadBishvilha': 'Beyahad Bishvilha',
    'behatsdaa': 'Behatsdaa',
}


@app.route('/')
def index():
    """Serve the credential input page."""
    token = request.args.get('token')
    if not token:
        return render_template('error.html', 
                             message='Missing authentication token. Please open this page from the Budgee app.')
    
    # Try to get connected accounts for this user
    connected_accounts = []
    try:
        decoded_token = verify_firebase_token(token)
        user_id = decoded_token['uid']
        connected_accounts = get_user_connected_accounts(user_id)
    except:
        pass  # Token might be invalid for display purposes, that's ok
    
    # Create display-friendly connected accounts list
    connected_display = [
        {'id': acc, 'name': COMPANY_DISPLAY_NAMES.get(acc, acc)}
        for acc in connected_accounts
    ]
    
    return render_template('index.html', 
                         token=token,
                         companies=COMPANY_DISPLAY_NAMES,
                         credential_fields=CREDENTIAL_FIELDS,
                         connected_accounts=connected_display)


@app.route('/submit-credentials', methods=['POST'])
def submit_credentials():
    """
    Receive and store encrypted credentials, then trigger initial scrape.
    Supports multiple accounts per user.
    
    Expected JSON body:
    {
        "token": "firebase_id_token",
        "companyId": "hapoalim",
        "credentials": {
            "username": "...",
            "password": "...",
            ...
        },
        "startDate": "2025-01-01",
        "consent": true
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
        
        token = data.get('token')
        company_id = data.get('companyId')
        credentials = data.get('credentials')
        start_date = data.get('startDate')
        consent = data.get('consent', False)
        
        if not all([token, company_id, credentials]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if not consent:
            return jsonify({'error': 'User consent is required'}), 400
        
        # Verify Firebase token
        try:
            decoded_token = verify_firebase_token(token)
            user_id = decoded_token['uid']
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
        
        # Validate company_id
        if company_id not in CREDENTIAL_FIELDS:
            return jsonify({'error': f'Invalid company: {company_id}'}), 400
        
        # Validate required credential fields for this company
        required_fields = CREDENTIAL_FIELDS[company_id]
        for field in required_fields:
            if not credentials.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Encrypt credentials
        encrypted = encrypt_credentials(credentials)
        
        # Save to Firebase (under user_id/company_id)
        save_user_credentials(user_id, company_id, encrypted)
        
        # Update status to pending
        update_scraper_status(user_id, 'pending', company_id=company_id)
        
        # Trigger immediate scrape
        scrape_result = trigger_scrape(user_id, company_id, credentials, start_date)
        
        if scrape_result.get('success'):
            return jsonify({
                'success': True,
                'message': 'Credentials saved and initial scrape completed successfully',
                'newTransactions': scrape_result.get('new_count', 0)
            })
        else:
            # Credentials saved but scrape failed
            return jsonify({
                'success': True,
                'message': 'Credentials saved. Scraping encountered an issue but will retry.',
                'scrapeError': scrape_result.get('error')
            })
    
    except Exception as e:
        logger.error(f"Error in submit_credentials: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/scrape-job', methods=['POST'])
def scrape_job():
    """
    Internal endpoint called by scheduler to run daily scrape jobs.
    Returns immediately and runs scraping in background thread.
    Requires scheduler secret for authentication.
    """
    try:
        # Verify scheduler secret
        auth_header = request.headers.get('Authorization')
        expected = f'Bearer {Config.SCHEDULER_SECRET}'
        
        if auth_header != expected:
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Get count of accounts to process (for the response)
        enabled_accounts = get_all_enabled_accounts()
        account_count = len(enabled_accounts)
        
        # Start background thread for scraping
        thread = threading.Thread(target=run_scrape_job_background)
        thread.daemon = True
        thread.start()
        
        # Return immediately
        logger.info(f"Scrape job started in background for {account_count} accounts")
        return jsonify({
            'status': 'started',
            'message': f'Scrape job started in background for {account_count} accounts'
        })
    
    except Exception as e:
        logger.error(f"Error starting scrape_job: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def run_scrape_job_background():
    """Run the actual scraping in background thread."""
    try:
        logger.info("Background scrape job started")
        
        # Get all accounts with scraping enabled
        enabled_accounts = get_all_enabled_accounts()
        
        results = {
            'processed': 0,
            'success': 0,
            'failed': 0
        }
        
        for user_id, company_id, account_data in enabled_accounts:
            results['processed'] += 1
            
            try:
                # Decrypt credentials
                encrypted = account_data.get('credentials')
                
                if not encrypted:
                    results['failed'] += 1
                    logger.error(f'{user_id}/{company_id}: Missing credentials')
                    continue
                
                credentials = decrypt_credentials(encrypted)
                
                # Update status to pending
                update_scraper_status(user_id, 'pending', company_id=company_id)
                
                # Trigger scrape (use last 30 days as default)
                start_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
                
                scrape_result = trigger_scrape(user_id, company_id, credentials, start_date)
                
                if scrape_result.get('success'):
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    logger.error(f'{user_id}/{company_id}: {scrape_result.get("error")}')
            
            except Exception as e:
                results['failed'] += 1
                logger.error(f'{user_id}/{company_id}: {str(e)}')
                update_scraper_status(user_id, 'error', str(e), company_id=company_id)
        
        logger.info(f"Background scrape job completed: {results['success']}/{results['processed']} successful")
    
    except Exception as e:
        logger.error(f"Error in background scrape job: {e}")


@app.route('/status/<user_id>', methods=['GET'])
def get_status(user_id):
    """Get scraping status for a user, including all connected accounts."""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return jsonify({'error': 'Missing authentication token'}), 401
        
        # Verify token and check user matches
        try:
            decoded_token = verify_firebase_token(token)
            if decoded_token['uid'] != user_id:
                return jsonify({'error': 'Unauthorized'}), 403
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
        
        # Get all user accounts
        user_accounts = get_user_credentials(user_id)
        
        if not user_accounts:
            return jsonify({
                'hasCredentials': False,
                'connectedAccounts': [],
                'scrapingEnabled': False
            })
        
        # Build list of connected accounts with their status
        connected_accounts = []
        for company_id, account_data in user_accounts.items():
            if isinstance(account_data, dict):
                connected_accounts.append({
                    'companyId': company_id,
                    'companyName': COMPANY_DISPLAY_NAMES.get(company_id, company_id),
                    'scrapingEnabled': account_data.get('scraping_enabled', False),
                    'lastScraped': account_data.get('last_scraped'),
                    'createdAt': account_data.get('created_at')
                })
        
        return jsonify({
            'hasCredentials': len(connected_accounts) > 0,
            'connectedAccounts': connected_accounts,
            'scrapingEnabled': any(acc['scrapingEnabled'] for acc in connected_accounts)
        })
    
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/delete-credentials', methods=['DELETE'])
def delete_credentials():
    """
    Allow users to delete their stored credentials.
    Can delete a specific account or all accounts.
    
    Query params:
        company_id: Optional - if provided, deletes only that company's credentials
    """
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        company_id = request.args.get('company_id')
        
        if not token:
            return jsonify({'error': 'Missing authentication token'}), 401
        
        # Verify token
        try:
            decoded_token = verify_firebase_token(token)
            user_id = decoded_token['uid']
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
        
        # Delete credentials (specific company or all)
        delete_user_credentials(user_id, company_id)
        
        # Update status
        from firebase_client import db, init_firebase
        init_firebase()
        
        remaining_accounts = get_user_connected_accounts(user_id)
        
        status_ref = db.reference(f'scraper_status/{user_id}')
        if remaining_accounts:
            # Still have some accounts, update status
            status_ref.update({
                'connected_accounts': remaining_accounts
            })
            message = f'Credentials for {company_id} deleted successfully'
        else:
            # No more accounts
            status_ref.set({
                'status': 'deleted',
                'has_credentials': False,
                'last_run': None,
                'error_message': None,
                'connected_accounts': []
            })
            message = 'All credentials deleted successfully'
        
        return jsonify({'success': True, 'message': message})
    
    except Exception as e:
        logger.error(f"Error in delete_credentials: {e}")
        return jsonify({'error': 'Internal server error'}), 500


def trigger_scrape(user_id: str, company_id: str, credentials: dict, start_date: str) -> dict:
    """
    Trigger a scrape request to the bank-scraper-service.
    
    Args:
        user_id: Firebase user ID
        company_id: Bank/card company identifier
        credentials: Decrypted credentials
        start_date: Start date for scraping (YYYY-MM-DD)
    
    Returns:
        Dict with 'success' boolean, optional 'error' message, and 'new_count' for new transactions
    """
    try:
        # Prepare request to scraper service
        scraper_url = f"{Config.SCRAPER_SERVICE_URL}/scrape"
        
        payload = {
            'companyId': company_id,
            'credentials': credentials,
            'startDate': start_date
        }
        
        # Call scraper service with generous timeout
        response = requests.post(
            scraper_url,
            json=payload,
            timeout=300  # 5 minutes
        )
        
        if response.status_code != 200:
            error_msg = f"Scraper service returned {response.status_code}"
            update_scraper_status(user_id, 'error', error_msg, company_id=company_id)
            return {'success': False, 'error': error_msg}
        
        result = response.json()
        
        if result.get('success'):
            # Save scraped expenses to Firebase (merges with existing)
            new_count = save_scraped_expenses(user_id, company_id, result)
            update_last_scraped(user_id, company_id)
            update_scraper_status(user_id, 'success', company_id=company_id)
            return {'success': True, 'new_count': new_count}
        else:
            error_msg = result.get('errorMessage', 'Unknown scraping error')
            update_scraper_status(user_id, 'error', error_msg, company_id=company_id)
            return {'success': False, 'error': error_msg}
    
    except requests.Timeout:
        error_msg = 'Scraping request timed out'
        update_scraper_status(user_id, 'error', error_msg, company_id=company_id)
        return {'success': False, 'error': error_msg}
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error triggering scrape for {user_id}/{company_id}: {error_msg}")
        update_scraper_status(user_id, 'error', error_msg, company_id=company_id)
        return {'success': False, 'error': error_msg}


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
