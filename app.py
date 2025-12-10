"""
Scraper Entry Point Service - Flask Application

This service provides a web interface for users to enter their bank credentials,
stores them securely, and orchestrates scraping jobs with the existing bank-scraper-service.
"""
import os
import logging
import requests
from flask import Flask, request, jsonify, render_template, redirect
from flask_cors import CORS
from config import Config
from encryption import encrypt_credentials, decrypt_credentials
from firebase_client import (
    verify_firebase_token,
    save_user_credentials,
    get_user_credentials,
    get_all_enabled_users,
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
    
    return render_template('index.html', 
                         token=token,
                         companies=COMPANY_DISPLAY_NAMES,
                         credential_fields=CREDENTIAL_FIELDS)


@app.route('/submit-credentials', methods=['POST'])
def submit_credentials():
    """
    Receive and store encrypted credentials, then trigger initial scrape.
    
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
        
        # Save to Firebase
        save_user_credentials(user_id, company_id, encrypted)
        
        # Update status to pending
        update_scraper_status(user_id, 'pending')
        
        # Trigger immediate scrape
        scrape_result = trigger_scrape(user_id, company_id, credentials, start_date)
        
        if scrape_result.get('success'):
            return jsonify({
                'success': True,
                'message': 'Credentials saved and initial scrape completed successfully'
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
    Requires scheduler secret for authentication.
    """
    try:
        # Verify scheduler secret
        auth_header = request.headers.get('Authorization')
        expected = f'Bearer {Config.SCHEDULER_SECRET}'
        
        if auth_header != expected:
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Get all users with scraping enabled
        enabled_users = get_all_enabled_users()
        
        results = {
            'processed': 0,
            'success': 0,
            'failed': 0,
            'errors': []
        }
        
        for user_id, user_data in enabled_users:
            results['processed'] += 1
            
            try:
                # Decrypt credentials
                encrypted = user_data.get('credentials')
                company_id = user_data.get('company_id')
                
                if not encrypted or not company_id:
                    results['failed'] += 1
                    results['errors'].append(f'{user_id}: Missing credentials or company_id')
                    continue
                
                credentials = decrypt_credentials(encrypted)
                
                # Update status to pending
                update_scraper_status(user_id, 'pending')
                
                # Trigger scrape (use last 30 days as default)
                from datetime import datetime, timedelta
                start_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')
                
                scrape_result = trigger_scrape(user_id, company_id, credentials, start_date)
                
                if scrape_result.get('success'):
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f'{user_id}: {scrape_result.get("error")}')
            
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f'{user_id}: {str(e)}')
                update_scraper_status(user_id, 'error', str(e))
        
        logger.info(f"Scrape job completed: {results['success']}/{results['processed']} successful")
        return jsonify(results)
    
    except Exception as e:
        logger.error(f"Error in scrape_job: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/status/<user_id>', methods=['GET'])
def get_status(user_id):
    """Get scraping status for a user."""
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
        
        # Get user credentials to check if they exist
        user_creds = get_user_credentials(user_id)
        
        return jsonify({
            'hasCredentials': user_creds is not None,
            'companyId': user_creds.get('company_id') if user_creds else None,
            'scrapingEnabled': user_creds.get('scraping_enabled', False) if user_creds else False,
            'lastScraped': user_creds.get('last_scraped') if user_creds else None
        })
    
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/delete-credentials', methods=['DELETE'])
def delete_credentials():
    """Allow users to delete their stored credentials."""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not token:
            return jsonify({'error': 'Missing authentication token'}), 401
        
        # Verify token
        try:
            decoded_token = verify_firebase_token(token)
            user_id = decoded_token['uid']
        except ValueError as e:
            return jsonify({'error': str(e)}), 401
        
        # Delete credentials
        delete_user_credentials(user_id)
        
        # Update status
        from firebase_client import db, init_firebase
        init_firebase()
        status_ref = db.reference(f'scraper_status/{user_id}')
        status_ref.set({
            'status': 'deleted',
            'has_credentials': False,
            'last_run': None,
            'error_message': None
        })
        
        return jsonify({'success': True, 'message': 'Credentials deleted successfully'})
    
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
        Dict with 'success' boolean and optional 'error' message
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
            update_scraper_status(user_id, 'error', error_msg)
            return {'success': False, 'error': error_msg}
        
        result = response.json()
        
        if result.get('success'):
            # Save scraped expenses to Firebase
            save_scraped_expenses(user_id, result)
            update_last_scraped(user_id)
            update_scraper_status(user_id, 'success')
            return {'success': True}
        else:
            error_msg = result.get('errorMessage', 'Unknown scraping error')
            update_scraper_status(user_id, 'error', error_msg)
            return {'success': False, 'error': error_msg}
    
    except requests.Timeout:
        error_msg = 'Scraping request timed out'
        update_scraper_status(user_id, 'error', error_msg)
        return {'success': False, 'error': error_msg}
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error triggering scrape for {user_id}: {error_msg}")
        update_scraper_status(user_id, 'error', error_msg)
        return {'success': False, 'error': error_msg}


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')

