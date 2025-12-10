# Daily Scheduler Setup

The scraper entry point service needs a daily trigger to run automated scrapes for all users with stored credentials.

## Endpoint

```
POST /scrape-job
Authorization: Bearer <SCHEDULER_SECRET>
```

The `SCHEDULER_SECRET` must match the environment variable configured in the service.

## Option 1: Koyeb Cron Jobs (Recommended for Koyeb deployment)

Koyeb supports cron jobs. Add this to your service configuration:

```yaml
cron:
  - schedule: "0 6 * * *"  # Every day at 6:00 AM UTC
    command: |
      curl -X POST https://your-service.koyeb.app/scrape-job \
        -H "Authorization: Bearer $SCHEDULER_SECRET"
```

## Option 2: External Cron Service

Use a free cron service like [cron-job.org](https://cron-job.org) or [EasyCron](https://www.easycron.com/):

1. Create an account
2. Add a new cron job:
   - URL: `https://your-service-url/scrape-job`
   - Method: POST
   - Headers: `Authorization: Bearer YOUR_SCHEDULER_SECRET`
   - Schedule: Every day at 6:00 AM (or your preferred time)

## Option 3: Google Cloud Scheduler

If using Google Cloud:

```bash
gcloud scheduler jobs create http daily-scrape-job \
  --schedule="0 6 * * *" \
  --uri="https://your-service-url/scrape-job" \
  --http-method=POST \
  --headers="Authorization=Bearer YOUR_SCHEDULER_SECRET" \
  --time-zone="Asia/Jerusalem"
```

## Option 4: GitHub Actions (Free)

Create `.github/workflows/daily-scrape.yml`:

```yaml
name: Daily Scrape

on:
  schedule:
    - cron: '0 6 * * *'  # 6 AM UTC daily
  workflow_dispatch:  # Allow manual trigger

jobs:
  trigger-scrape:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger scrape job
        run: |
          curl -X POST ${{ secrets.SCRAPER_ENTRY_POINT_URL }}/scrape-job \
            -H "Authorization: Bearer ${{ secrets.SCHEDULER_SECRET }}" \
            -H "Content-Type: application/json"
```

Add these secrets to your GitHub repository:
- `SCRAPER_ENTRY_POINT_URL`: Your deployed service URL
- `SCHEDULER_SECRET`: The scheduler secret from your environment

## Testing the Scheduler

You can manually test the endpoint:

```bash
curl -X POST https://your-service-url/scrape-job \
  -H "Authorization: Bearer YOUR_SCHEDULER_SECRET" \
  -H "Content-Type: application/json"
```

Expected response:
```json
{
  "processed": 5,
  "success": 4,
  "failed": 1,
  "errors": ["user123: Connection timeout"]
}
```

## Timezone Considerations

- Koyeb/Cloud services typically use UTC
- For Israel (Asia/Jerusalem), 6 AM local time = 4 AM UTC (winter) or 3 AM UTC (summer)
- Adjust your cron schedule accordingly

