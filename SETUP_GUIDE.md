# 🏛️ Government Scheme Hub — Complete Setup Guide

## ──────────────────────────────────────────
## STEP 1: Run Locally (Testing)
## ──────────────────────────────────────────

### Install dependencies
```
pip install -r requirements.txt
```

### Create .env file
```
copy .env.example .env       ← Windows
cp .env.example .env         ← Mac/Linux
```
Then open .env and set at minimum:
- SECRET_KEY = any random string
- MONGO_URI  = mongodb://localhost:27017/govscheme  (if MongoDB installed locally)

### Start MongoDB locally
```
mongod
```

### Run the app
```
python run.py
```

Open browser → http://127.0.0.1:5000


## ──────────────────────────────────────────
## STEP 2: Test Payment (Razorpay Test Mode)
## ──────────────────────────────────────────

### How to get Razorpay TEST keys (free, no KYC needed):

1. Go to https://dashboard.razorpay.com → Sign up (free)
2. In Dashboard → click "Test Mode" toggle (top right)  
3. Go to Settings → API Keys → Generate Test Key
4. Copy Key ID and Key Secret into your .env:
   RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXXXX
   RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX

### How to make a TEST payment:

When you click "Upgrade to Pro" on the website:
- Card Number : 4111 1111 1111 1111
- Expiry      : Any future date (e.g. 12/26)
- CVV         : Any 3 digits (e.g. 123)
- OTP         : 1234  (Razorpay test OTP)

After successful payment → Pro is activated instantly.

### Testing WITHOUT Razorpay keys:

If RAZORPAY_KEY_ID is empty in .env:
- Click "Upgrade to Pro" page
- Click the "🧪 Activate Demo Pro (Dev Only)" button
- Pro activates instantly without any payment
- Use this for testing all Pro features


## ──────────────────────────────────────────
## STEP 3: Add AI Assistant (Free)
## ──────────────────────────────────────────

1. Go to https://aistudio.google.com/app/apikey
2. Click "Create API Key" (free, no credit card)
3. Copy key → add to .env:
   GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXX

If you skip this, AI Assistant still works using smart keyword matching.


## ──────────────────────────────────────────
## STEP 4: Deploy to Internet (Render.com)
## ──────────────────────────────────────────

### 4a. Create MongoDB Atlas (free cloud database)

1. Go to https://cloud.mongodb.com → Sign up free
2. Create a new project → Create FREE cluster (M0)
3. Database Access → Add Database User
   - Username: govscheme_user
   - Password: (generate a strong password, save it)
   - Role: Read and write to any database
4. Network Access → Add IP Address → Allow Access from Anywhere (0.0.0.0/0)
5. Clusters → Connect → Drivers → Copy connection string
   Looks like: mongodb+srv://govscheme_user:PASSWORD@cluster0.xxxxx.mongodb.net/govscheme
6. Replace <password> in the string with your actual password

### 4b. Push code to GitHub

```
git init
git add .
git commit -m "Government Scheme Hub"
git remote add origin https://github.com/YOUR_USERNAME/govscheme.git
git push -u origin main
```

### 4c. Deploy on Render

1. Go to https://render.com → Sign up with GitHub
2. New → Web Service → Connect your GitHub repo
3. Settings:
   - Name       : govt-scheme-hub
   - Environment: Python
   - Build Cmd  : pip install -r requirements.txt
   - Start Cmd  : gunicorn run:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
4. Environment Variables → Add all 5 variables:

   SECRET_KEY          = (click "Generate" button)
   MONGO_URI           = mongodb+srv://user:pass@cluster.mongodb.net/govscheme
   RAZORPAY_KEY_ID     = rzp_live_XXXXXXXXXXXXXXXX   ← live key after KYC
   RAZORPAY_KEY_SECRET = XXXXXXXXXXXXXXXXXXXXXXXX
   GEMINI_API_KEY      = AIzaSyXXXXXXXXXXXXXXXXXXXX  ← optional

5. Click Deploy!

Your site will be live at: https://govt-scheme-hub.onrender.com


## ──────────────────────────────────────────
## STEP 5: Live Payments (Razorpay LIVE keys)
## ──────────────────────────────────────────

For REAL money collection:
1. Go to Razorpay Dashboard → Complete KYC (business details)
2. KYC takes 1-3 days to approve
3. After approval → Switch to LIVE MODE
4. Settings → API Keys → Generate LIVE Key
5. Replace test keys in Render environment variables:
   RAZORPAY_KEY_ID     = rzp_live_XXXXXXXXXXXXXXXX
   RAZORPAY_KEY_SECRET = XXXXXXXXXXXXXXXXXXXXXXXX
6. Redeploy on Render

Price is set to ₹499/year. To change:
- Open app.py → line: PRO_PRICE = 49900  (paise, so 49900 = ₹499)
- Change to whatever price you want × 100


## ──────────────────────────────────────────
## SUMMARY: What's in this project
## ──────────────────────────────────────────

FREE Features:
✅ Browse 1200+ central & state govt schemes
✅ Search and filter by category/state
✅ Save schemes to your list
✅ Apply for schemes (track locally)
✅ User registration & login

PRO Features (₹499/year):
🔍 Eligibility Check — AI matches schemes to your profile
🤖 AI Assistant     — Chat about any scheme in English/Hinglish
📁 Document Vault   — Store Aadhaar, PAN, certificates
📊 Progress Tracker — Timeline view of all applications

Backend:
- Flask (Python web framework)
- MongoDB (database)
- Scrapers run every hour from myscheme.gov.in API
- Razorpay for payments
- Gemini AI for chatbot

