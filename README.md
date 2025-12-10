# Scraper Entry Point Service

A Flask web service that provides a secure interface for users to enter their bank/credit card credentials and orchestrates scraping jobs with the bank-scraper-service.

## Features

- Web UI for credential input (accessible via browser from the Budgee app)
- Firebase Auth token verification
- AES-256-GCM encryption for credential storage
- Integration with existing bank-scraper-service
- Daily automated scraping via scheduler endpoint
- Results pushed to Firebase Realtime Database

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

### 3. Generate Encryption Key

```bash
python encryption.py
```

Copy the generated key to your `.env` file.

### 4. Firebase Credentials

Download your Firebase Admin SDK credentials JSON file and save it as `firebase-credentials.json` (or update the path in `.env`).

### 5. Run Locally

```bash
python app.py
```

Or with gunicorn:

```bash
gunicorn --bind 0.0.0.0:8080 app:app
```

## Deployment (Koyeb)

### 1. Build and Push Docker Image

```bash
docker build -t scraper-entry-point .
docker tag scraper-entry-point your-registry/scraper-entry-point
docker push your-registry/scraper-entry-point
```

### 2. Set Environment Variables in Koyeb

Set all the variables from `.env.example` in your Koyeb service configuration.

### 3. Set Up Daily Scheduler

Use a cron service or Koyeb's scheduled jobs to call:

```
POST /scrape-job
Authorization: Bearer <SCHEDULER_SECRET>
```

Every day at your preferred time (e.g., 6:00 AM).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI for credential input |
| `/submit-credentials` | POST | Submit and store credentials |
| `/scrape-job` | POST | Trigger daily scrape (scheduler) |
| `/status/<user_id>` | GET | Check scraping status |
| `/delete-credentials` | DELETE | Delete stored credentials |
| `/health` | GET | Health check |

## Security

- All credentials are encrypted with AES-256-GCM before storage
- Firebase ID tokens are verified for all user operations
- HTTPS required for all communication
- Scheduler endpoint protected by secret token
- No credentials logged or stored in plain text

