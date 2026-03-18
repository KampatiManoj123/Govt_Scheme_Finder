import os
"""
Entry point — seeds DB and starts Flask app with hourly scraper
Run locally  : python run.py
Production   : gunicorn run:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
"""
import logging
logging.basicConfig(level=logging.INFO)

from app import app, mongo
from scrapers.scheme_scraper import seed_sample_data, start_scheduler

with app.app_context():
    try:
        seed_sample_data(mongo)
        print("✅ Database initialized")
    except Exception as e:
        print(f"⚠️  DB init warning: {e}")

    try:
        scheduler = start_scheduler(mongo)
        print("✅ Hourly scraper started")
    except Exception as e:
        print(f"⚠️  Scheduler warning: {e}")

if __name__ == "__main__":
    print("🚀 Starting Government Scheme Hub")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)