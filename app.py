from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import os, hmac, hashlib, uuid, re, random
import razorpay
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'govscheme-super-secret-key-2024')
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/govscheme')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

RAZORPAY_KEY_ID     = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY', '')

# Flask-Mail config (Gmail SMTP)
app.config['MAIL_SERVER']         = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']           = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USE_SSL']        = False
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = (
    'Government Scheme Hub',
    os.environ.get('MAIL_USERNAME', 'noreply@govscheme.in')
)

mongo        = PyMongo(app)
bcrypt       = Bcrypt(app)
mail         = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ── USER CLASS ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, user_data):
        self.id       = str(user_data['_id'])
        self.username = user_data['username']
        self.email    = user_data['email']
        self.is_pro   = user_data.get('is_pro', False)
        self.profile  = user_data.get('profile', {})

    def get_id(self):
        return self.id


@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except Exception:
        pass
    return None

INDIAN_STATES = [
    "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh",
    "Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka",
    "Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram",
    "Nagaland","Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu",
    "Telangana","Tripura","Uttar Pradesh","Uttarakhand","West Bengal",
    "Andaman and Nicobar Islands","Chandigarh","Dadra and Nagar Haveli",
    "Daman and Diu","Delhi","Jammu and Kashmir","Ladakh","Lakshadweep","Puducherry"
]

CATEGORIES = [
    {"id": "agriculture", "label": "Agriculture",        "icon": "🌾"},
    {"id": "farmer",      "label": "Farmer Welfare",     "icon": "👨‍🌾"},
    {"id": "healthcare",  "label": "Healthcare",          "icon": "🏥"},
    {"id": "women",       "label": "Women & Child",       "icon": "👩‍👧"},
    {"id": "education",   "label": "Education",           "icon": "📚"},
    {"id": "housing",     "label": "Housing",             "icon": "🏠"},
    {"id": "employment",  "label": "Employment",          "icon": "💼"},
    {"id": "finance",     "label": "Finance & Credit",    "icon": "💰"},
    {"id": "social",      "label": "Social Welfare",      "icon": "🤝"},
    {"id": "skill",       "label": "Skill Development",   "icon": "🎯"},
    {"id": "msme",        "label": "MSME / Business",     "icon": "🏭"},
    {"id": "pension",     "label": "Pension & Insurance", "icon": "🛡️"},
    {"id": "disability",  "label": "Disability",          "icon": "♿"},
    {"id": "minority",    "label": "Minority Welfare",    "icon": "🕌"},
    {"id": "digital",     "label": "Digital India",       "icon": "💻"},
    {"id": "environment", "label": "Environment",         "icon": "🌱"},
    {"id": "tribal",      "label": "Tribal Welfare",      "icon": "🌿"},
    {"id": "transport",   "label": "Transport",           "icon": "🚌"},
    {"id": "sports",      "label": "Sports & Youth",      "icon": "⚽"},
    {"id": "other",       "label": "Other",               "icon": "📋"},
]


# ════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        if mongo.db.users.find_one({'$or': [{'username': username}, {'email': email}]}):
            flash('Username or email already exists.', 'danger')
            return render_template('register.html')
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        mongo.db.users.insert_one({
            'username': username, 'email': email, 'password': hashed_pw,
            'is_pro': False, 'profile': {}, 'saved_schemes': [],
            'applications': [], 'documents': [], 'chat_history': [],
            'created_at': datetime.utcnow()
        })
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password   = request.form.get('password', '')
        user_data  = mongo.db.users.find_one({
            '$or': [{'username': identifier}, {'email': identifier.lower()}]
        })
        if user_data and bcrypt.check_password_hash(user_data['password'], password):
            login_user(User(user_data), remember=True)
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# ════════════════════════════════════════════════════════
# FORGOT PASSWORD — OTP FLOW
# ════════════════════════════════════════════════════════

def send_otp_email(email, otp):
    """Send OTP email. Returns True on success, False on failure."""
    try:
        msg      = Message(
            subject    = 'Your Password Reset OTP — Government Scheme Hub',
            recipients = [email]
        )
        msg.html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 0;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,0.08);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,#FF6B35,#f7931e);padding:32px 40px;text-align:center;">
            <div style="display:inline-block;background:rgba(255,255,255,0.2);border-radius:8px;
                        padding:6px 14px;margin-bottom:12px;">
              <span style="color:#fff;font-size:13px;font-weight:700;letter-spacing:2px;">
                🏛️ GOVERNMENT SCHEME HUB
              </span>
            </div>
            <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;">Password Reset OTP</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:40px 40px 32px;">
            <p style="margin:0 0 8px;color:#444;font-size:15px;line-height:1.6;">Hi there,</p>
            <p style="margin:0 0 28px;color:#555;font-size:15px;line-height:1.6;">
              We received a request to reset your password. Use the OTP below to continue.
            </p>
            <div style="background:#fff8f4;border:2px dashed #FF6B35;border-radius:12px;
                        padding:28px 20px;text-align:center;margin-bottom:28px;">
              <p style="margin:0 0 8px;color:#888;font-size:12px;
                         text-transform:uppercase;letter-spacing:2px;">Your One-Time Password</p>
              <div style="font-size:42px;font-weight:800;letter-spacing:16px;
                          color:#FF6B35;font-family:'Courier New',monospace;">{otp}</div>
              <p style="margin:12px 0 0;color:#999;font-size:12px;">
                ⏱️ Valid for <strong>2 minutes</strong>
              </p>
            </div>
            <p style="margin:0;color:#555;font-size:14px;line-height:1.6;">
              If you didn't request a password reset, you can safely ignore this email.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8f9fa;padding:20px 40px;border-top:1px solid #eee;text-align:center;">
            <p style="margin:0;color:#aaa;font-size:12px;">
              © 2024 Government Scheme Hub &nbsp;|&nbsp; Do not reply to this email.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[MAIL ERROR] {e}")
        return False


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('forgot_password.html')

        user = mongo.db.users.find_one({'email': email})
        if not user:
            flash('No account found with that email.', 'danger')
            return render_template('forgot_password.html')

        otp     = str(random.randint(100000, 999999))
        # OTP valid for 2 minutes
        expires = datetime.utcnow() + timedelta(minutes=2)
        sent_at = datetime.utcnow()

        mongo.db.users.update_one(
            {'email': email},
            {'$set': {
                'reset_otp':         otp,
                'reset_otp_expires': expires,
                'reset_otp_sent_at': sent_at
            }}
        )

        success = send_otp_email(email, otp)

        if success:
            session['reset_email']   = email
            session['otp_sent_at']   = sent_at.isoformat()
            flash('OTP sent to your email. Check your inbox (and spam folder).', 'success')
            return redirect(url_for('verify_otp'))
        else:
            flash('Failed to send OTP. Please check mail configuration or try again.', 'danger')
            return render_template('forgot_password.html')

    return render_template('forgot_password.html')


@app.route('/resend-otp', methods=['POST'])
def resend_otp():
    """Resend OTP — only allowed after 2 min cooldown has passed."""
    email = session.get('reset_email', '')
    if not email:
        return jsonify({'success': False, 'error': 'Session expired'}), 400

    user = mongo.db.users.find_one({'email': email})
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 400

    # Generate new OTP and reset timer
    otp     = str(random.randint(100000, 999999))
    expires = datetime.utcnow() + timedelta(minutes=2)
    sent_at = datetime.utcnow()

    mongo.db.users.update_one(
        {'email': email},
        {'$set': {
            'reset_otp':         otp,
            'reset_otp_expires': expires,
            'reset_otp_sent_at': sent_at
        }}
    )

    success = send_otp_email(email, otp)
    if success:
        session['otp_sent_at'] = sent_at.isoformat()
        return jsonify({'success': True, 'sent_at': sent_at.isoformat()})
    else:
        return jsonify({'success': False, 'error': 'Failed to send email'}), 500


@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        flash('Session expired. Please start again.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        otp_input = request.form.get('otp', '').strip()
        email     = session.get('reset_email', '')

        if not email:
            flash('Session expired. Please start again.', 'danger')
            return redirect(url_for('forgot_password'))

        user = mongo.db.users.find_one({'email': email})
        if not user:
            flash('Invalid session.', 'danger')
            return redirect(url_for('forgot_password'))

        stored_otp = user.get('reset_otp', '')
        expires    = user.get('reset_otp_expires')

        if not stored_otp:
            flash('OTP not found. Please request a new one.', 'danger')
            return redirect(url_for('forgot_password'))

        if expires and datetime.utcnow() > expires:
            flash('OTP expired. Please request a new one.', 'danger')
            return redirect(url_for('forgot_password'))

        if otp_input != stored_otp:
            flash('Invalid OTP. Please try again.', 'danger')
            return render_template('verify_otp.html',
                                   otp_sent_at=session.get('otp_sent_at', ''))

        # OTP verified — clear from DB (one-time use)
        mongo.db.users.update_one(
            {'email': email},
            {'$unset': {'reset_otp': '', 'reset_otp_expires': '', 'reset_otp_sent_at': ''}}
        )
        session['otp_verified'] = True
        return redirect(url_for('reset_password'))

    return render_template('verify_otp.html',
                           otp_sent_at=session.get('otp_sent_at', ''))


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or not session.get('reset_email'):
        flash('Please verify OTP first.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password  = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('reset_password.html')

        if password != password2:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html')

        email     = session.get('reset_email')
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        mongo.db.users.update_one(
            {'email': email},
            {'$set':   {'password': hashed_pw},
             '$unset': {'reset_otp': '', 'reset_otp_expires': '', 'reset_otp_sent_at': ''}}
        )

        session.pop('reset_email', None)
        session.pop('otp_verified', None)
        session.pop('otp_sent_at', None)

        flash('Password reset successfully! Please login with your new password.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html')


# ════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    user_data   = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    saved_count = len(user_data.get('saved_schemes', []))
    apps        = user_data.get('applications', [])
    app_count   = len(apps)

    one_week_ago = datetime.utcnow() - timedelta(days=7)
    new_schemes  = list(mongo.db.schemes.find({'scraped_at': {'$gte': one_week_ago}}).limit(8))
    new_count    = len(new_schemes)

    profile = user_data.get('profile', {})
    state   = profile.get('state', '')
    cat     = profile.get('category', '')
    query   = {}
    if state:
        query['$or'] = [{'level': 'central'}, {'state': state}]
    if cat:
        query['category'] = cat
    matched     = list(mongo.db.schemes.find(query).limit(48))
    top_matches = matched[:6] if current_user.is_pro else []

    profile_fields = ['name','age','gender','state','occupation','income','category']
    filled      = sum(1 for f in profile_fields if profile.get(f))
    profile_pct = int((filled / len(profile_fields)) * 100)

    saved_ids     = user_data.get('saved_schemes', [])
    saved_details = []
    for sid in saved_ids[:6]:
        try:
            s = mongo.db.schemes.find_one({'_id': ObjectId(sid)})
            if s:
                saved_details.append(s)
        except Exception:
            pass

    return render_template('dashboard.html',
        user=user_data, saved_count=saved_count, app_count=app_count,
        new_count=new_count, new_schemes=new_schemes[:4],
        top_matches=top_matches, matched_count=len(matched),
        profile_pct=profile_pct, saved_details=saved_details,
        recent_apps=apps[-5:][::-1], categories=CATEGORIES
    )


# ════════════════════════════════════════════════════════
# SCHEMES
# ════════════════════════════════════════════════════════

@app.route('/schemes')
@login_required
def browse_schemes():
    level      = request.args.get('level', '')
    category   = request.args.get('category', '')
    state      = request.args.get('state', '')
    search     = request.args.get('q', '')
    apply_mode = request.args.get('apply_mode', '')
    page       = max(1, int(request.args.get('page', 1)))
    per_page   = 20

    query = {}
    if level:
        query['level'] = level
    if category:
        query['category'] = category
    if state and level == 'state':
        query['state'] = state
    if apply_mode:
        query['apply_mode'] = apply_mode
    if search:
        query['$or'] = [
            {'title':       {'$regex': search, '$options': 'i'}},
            {'description': {'$regex': search, '$options': 'i'}}
        ]

    total   = mongo.db.schemes.count_documents(query)
    schemes = list(mongo.db.schemes.find(query).skip((page-1)*per_page).limit(per_page))
    cat_counts = {}
    for c in CATEGORIES:
        q = {'category': c['id']}
        if level:
            q['level'] = level
        if apply_mode:
            q['apply_mode'] = apply_mode
        cat_counts[c['id']] = mongo.db.schemes.count_documents(q)

    return render_template('schemes.html',
        schemes=schemes, total=total, page=page, per_page=per_page,
        categories=CATEGORIES, cat_counts=cat_counts,
        states=INDIAN_STATES, current_level=level,
        current_category=category, current_state=state,
        current_apply_mode=apply_mode, search=search
    )


@app.route('/scheme/<scheme_id>')
@login_required
def scheme_detail(scheme_id):
    scheme = mongo.db.schemes.find_one({'_id': ObjectId(scheme_id)})
    if not scheme:
        flash('Scheme not found.', 'danger')
        return redirect(url_for('browse_schemes'))
    user_data  = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    is_saved   = scheme_id in [str(s) for s in user_data.get('saved_schemes', [])]
    is_applied = any(a['scheme_id'] == scheme_id for a in user_data.get('applications', []))
    related    = list(mongo.db.schemes.find({
        'category': scheme.get('category'),
        '_id': {'$ne': scheme['_id']}
    }).limit(4))
    return render_template('scheme_detail.html', scheme=scheme,
                           is_saved=is_saved, is_applied=is_applied, related=related)


# ════════════════════════════════════════════════════════
# SAVE / UNSAVE
# ════════════════════════════════════════════════════════

@app.route('/api/save-scheme', methods=['POST'])
@login_required
def api_save_scheme():
    data      = request.get_json()
    scheme_id = data.get('scheme_id')
    action    = data.get('action', 'save')
    if action == 'save':
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$addToSet': {'saved_schemes': scheme_id}}
        )
    else:
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$pull': {'saved_schemes': scheme_id}}
        )
    return jsonify({'success': True})


# ════════════════════════════════════════════════════════
# APPLY
# ════════════════════════════════════════════════════════

@app.route('/apply/<scheme_id>', methods=['GET', 'POST'])
@login_required
def apply_scheme(scheme_id):
    scheme = mongo.db.schemes.find_one({'_id': ObjectId(scheme_id)})
    if not scheme:
        return redirect(url_for('browse_schemes'))
    if request.method == 'POST':
        user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
        already   = any(a['scheme_id'] == scheme_id for a in user_data.get('applications', []))
        if already:
            flash('You have already applied for this scheme.', 'info')
            return redirect(url_for('my_applications'))
        application = {
            'scheme_id':       scheme_id,
            'scheme_title':    scheme['title'],
            'scheme_category': scheme.get('category', ''),
            'scheme_level':    scheme.get('level', ''),
            'scheme_state':    scheme.get('state', ''),
            'applied_at':      datetime.utcnow(),
            'status':          'pending',
            'status_history':  [{'status': 'pending',
                                  'date': datetime.utcnow().isoformat(),
                                  'note': 'Application submitted successfully'}]
        }
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$push': {'applications': application}}
        )
        flash('Application submitted successfully!', 'success')
        return redirect(url_for('my_applications'))
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    return render_template('apply.html', scheme=scheme, profile=user_data.get('profile', {}))


# ════════════════════════════════════════════════════════
# MY APPLICATIONS
# ════════════════════════════════════════════════════════

@app.route('/my-applications')
@login_required
def my_applications():
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    apps = sorted(user_data.get('applications', []),
                  key=lambda x: x.get('applied_at', datetime.min), reverse=True)
    return render_template('my_applications.html', applications=apps)


@app.route('/application-status/<scheme_id>')
@login_required
def application_status(scheme_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    app_data  = next((a for a in user_data.get('applications', [])
                      if a['scheme_id'] == scheme_id), None)
    if not app_data:
        flash('Application not found.', 'danger')
        return redirect(url_for('my_applications'))
    return render_template('application_status.html', application=app_data)


# ════════════════════════════════════════════════════════
# SAVED SCHEMES
# ════════════════════════════════════════════════════════

@app.route('/saved-schemes')
@login_required
def saved_schemes():
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    schemes   = []
    for sid in user_data.get('saved_schemes', []):
        try:
            s = mongo.db.schemes.find_one({'_id': ObjectId(sid)})
            if s:
                schemes.append(s)
        except Exception:
            pass
    return render_template('saved_schemes.html', schemes=schemes)


# ════════════════════════════════════════════════════════
# PROFILE
# ════════════════════════════════════════════════════════

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    if request.method == 'POST':
        profile_data = {k: request.form.get(k, '') for k in
            ['name','age','gender','state','district','occupation','income',
             'category','education','differently_abled','minority','bpl']}
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'profile': profile_data}}
        )
        flash('Profile updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user_data,
                           states=INDIAN_STATES, categories=CATEGORIES)


# ════════════════════════════════════════════════════════
# PRO: ELIGIBILITY CHECK
# ════════════════════════════════════════════════════════

@app.route('/eligibility-check')
@login_required
def eligibility_check():
    if not current_user.is_pro:
        return redirect(url_for('upgrade'))
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    profile   = user_data.get('profile', {})

    if not any(profile.values()):
        flash('Please complete your profile first.', 'warning')
        return redirect(url_for('profile'))

    or_conditions = [{'level': 'central'}]
    if profile.get('state'):
        or_conditions.append({'state': profile['state']})
    all_schemes = list(mongo.db.schemes.find({'$or': or_conditions}))

    def score(scheme):
        s    = 1
        text = ((scheme.get('eligibility') or '') + ' ' +
                (scheme.get('beneficiary') or '') + ' ' +
                (scheme.get('description') or '')).lower()
        if profile.get('occupation') and profile['occupation'].lower() in text: s += 3
        if profile.get('category')   and profile['category'].lower()   in text: s += 2
        if profile.get('gender') == 'female' and any(
            w in text for w in ['women','woman','girl','mahila','beti']): s += 3
        if profile.get('bpl') == 'yes' and any(
            w in text for w in ['bpl','below poverty','poor']): s += 3
        return s

    eligible = sorted(all_schemes, key=score, reverse=True)[:30]
    return render_template('eligibility.html', schemes=eligible,
                           profile=profile, total_matched=len(eligible))


# ════════════════════════════════════════════════════════
# PRO: AI ASSISTANT
# ════════════════════════════════════════════════════════

@app.route('/ai-assistant')
@login_required
def ai_assistant():
    if not current_user.is_pro:
        return redirect(url_for('upgrade'))
    user_data    = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    chat_history = user_data.get('chat_history', [])[-20:]
    return render_template('ai_assistant.html', chat_history=chat_history)


@app.route('/api/ai-chat', methods=['POST'])
@login_required
def api_ai_chat():
    if not current_user.is_pro:
        return jsonify({'error': 'Pro required'}), 403

    data         = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    user_data       = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    profile         = user_data.get('profile', {})
    schemes_context = list(mongo.db.schemes.find({}, {
        'title':1,'benefits':1,'eligibility':1,'category':1,'level':1,'state':1
    }).limit(50))

    try:
        import requests as req
        if GEMINI_API_KEY:
            schemes_text = '\n'.join([
                f"- {s['title']}: {s.get('benefits','')} | {s.get('eligibility','')[:80]}"
                for s in schemes_context
            ])
            system = (f"You are a helpful Indian Government Schemes Assistant. "
                      f"User: State={profile.get('state','')}, "
                      f"Occupation={profile.get('occupation','')}, "
                      f"Income={profile.get('income','')}.\n"
                      f"Schemes:\n{schemes_text}\n"
                      f"Answer in English or Hinglish. Be concise.")
            resp = req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": f"{system}\n\nUser: {user_message}"}]}],
                      "generationConfig": {"maxOutputTokens": 500}},
                timeout=15
            )
            if resp.status_code == 200:
                ai_response = resp.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                ai_response = _fallback_response(user_message, schemes_context, profile)
        else:
            ai_response = _fallback_response(user_message, schemes_context, profile)

        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$push': {'chat_history': {
                'user': user_message, 'assistant': ai_response,
                'timestamp': datetime.utcnow().isoformat()
            }}}
        )
        return jsonify({'response': ai_response})
    except Exception:
        return jsonify({'response': _fallback_response(user_message, schemes_context, profile)})
    

def _fallback_response(message, schemes, profile):
    msg   = message.lower()
    cats  = {
        'agriculture': ['farmer','crop','kisan','agriculture','rythu'],
        'healthcare':  ['health','hospital','medical','aarogya'],
        'housing':     ['house','home','awas','housing'],
        'education':   ['education','scholarship','study','school'],
        'employment':  ['job','work','employment','rozgar'],
        'women':       ['women','girl','mahila','beti'],
        'finance':     ['loan','credit','mudra','money'],
        'skill':       ['skill','training','pmkvy'],
    }
    matched = [cat for cat, kws in cats.items() if any(k in msg for k in kws)]
    results = [s for s in schemes if s.get('category') in matched] or schemes[:5]
    resp    = "Based on your query, here are relevant schemes:\n\n"
    for s in results[:4]:
        resp += f"*{s['title']}*\nBenefits: {s.get('benefits','Visit official website')}\n\n"
    resp += "\nVisit the official website or nearest CSC to apply."
    return resp


# ════════════════════════════════════════════════════════
# PRO: DOCUMENT VAULT
# ════════════════════════════════════════════════════════

@app.route('/document-vault')
@login_required
def document_vault():
    if not current_user.is_pro:
        return redirect(url_for('upgrade'))
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    return render_template('document_vault.html', documents=user_data.get('documents', []))


@app.route('/api/upload-document', methods=['POST'])
@login_required
def upload_document():
    if not current_user.is_pro:
        return jsonify({'error': 'Pro required'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file     = request.files['file']
    doc_type = request.form.get('doc_type', 'Other')
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in {'pdf','jpg','jpeg','png','doc','docx'}:
        return jsonify({'error': 'File type not allowed'}), 400
    data = file.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({'error': 'Max 5MB'}), 400
    import base64
    mongo.db.users.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$push': {'documents': {
            'id': str(uuid.uuid4()), 'name': file.filename,
            'type': doc_type, 'ext': ext, 'size': len(data),
            'data': base64.b64encode(data).decode('utf-8'),
            'uploaded_at': datetime.utcnow().isoformat()
        }}}
    )
    return jsonify({'success': True})


@app.route('/api/delete-document', methods=['POST'])
@login_required
def delete_document():
    if not current_user.is_pro:
        return jsonify({'error': 'Pro required'}), 403
    doc_id = request.get_json().get('doc_id')
    mongo.db.users.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$pull': {'documents': {'id': doc_id}}}
    )
    return jsonify({'success': True})


@app.route('/api/view-document/<doc_id>')
@login_required
def view_document(doc_id):
    import base64
    from flask import make_response
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    docs      = user_data.get('documents', [])
    doc       = next((d for d in docs if d['id'] == doc_id), None)
    if not doc:
        return 'Not found', 404
    data     = base64.b64decode(doc['data'])
    ext      = doc.get('ext', 'pdf')
    mimetypes = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                 'png': 'image/png', 'doc': 'application/msword',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    mime     = mimetypes.get(ext, 'application/octet-stream')
    resp     = make_response(data)
    resp.headers['Content-Type']        = mime
    resp.headers['Content-Disposition'] = f'inline; filename="{doc["name"]}"'
    return resp


@app.route('/api/download-document/<doc_id>')
@login_required
def download_document(doc_id):
    import base64
    from flask import make_response
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    docs      = user_data.get('documents', [])
    doc       = next((d for d in docs if d['id'] == doc_id), None)
    if not doc:
        return 'Not found', 404
    data     = base64.b64decode(doc['data'])
    ext      = doc.get('ext', 'pdf')
    mimetypes = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                 'png': 'image/png', 'doc': 'application/msword',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
    mime     = mimetypes.get(ext, 'application/octet-stream')
    resp     = make_response(data)
    resp.headers['Content-Type']        = mime
    resp.headers['Content-Disposition'] = f'attachment; filename="{doc["name"]}"'
    return resp


# ════════════════════════════════════════════════════════
# PRO: PROGRESS TRACKER
# ════════════════════════════════════════════════════════

@app.route('/progress-tracker')
@login_required
def progress_tracker():
    if not current_user.is_pro:
        return redirect(url_for('upgrade'))
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    apps      = user_data.get('applications', [])
    enriched  = []
    for app in apps:
        scheme = None
        try:
            scheme = mongo.db.schemes.find_one({'_id': ObjectId(app['scheme_id'])})
        except Exception:
            pass
        enriched.append({**app, 'scheme': scheme})
    stats = {
        'total':     len(apps),
        'pending':   sum(1 for a in apps if a.get('status') == 'pending'),
        'approved':  sum(1 for a in apps if a.get('status') == 'approved'),
        'rejected':  sum(1 for a in apps if a.get('status') == 'rejected'),
        'in_review': sum(1 for a in apps if a.get('status') == 'in_review'),
    }
    return render_template('progress_tracker.html', applications=enriched, stats=stats)


@app.route('/api/update-application-status', methods=['POST'])
@login_required
def update_application_status():
    if not current_user.is_pro:
        return jsonify({'error': 'Pro required'}), 403
    data       = request.get_json()
    scheme_id  = data.get('scheme_id')
    new_status = data.get('status')
    note       = data.get('note', '')
    if new_status not in ['pending','in_review','approved','rejected','documents_required']:
        return jsonify({'error': 'Invalid status'}), 400
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    apps      = user_data.get('applications', [])
    updated   = False
    for app in apps:
        if app['scheme_id'] == scheme_id:
            app['status'] = new_status
            if 'status_history' not in app:
                app['status_history'] = []
            app['status_history'].append({
                'status': new_status,
                'date':   datetime.utcnow().isoformat(),
                'note':   note or f'Status updated to {new_status}'
            })
            updated = True
            break
    if updated:
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'applications': apps}}
        )
    return jsonify({'success': updated})


# ════════════════════════════════════════════════════════
# UPGRADE PAGE
# ════════════════════════════════════════════════════════

@app.route('/upgrade')
@login_required
def upgrade():
    if current_user.is_pro:
        flash('You are already a Pro member!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('upgrade.html', razorpay_key=RAZORPAY_KEY_ID)


# ════════════════════════════════════════════════════════
# SAVE PHONE
# ════════════════════════════════════════════════════════

@app.route('/api/save-phone', methods=['POST'])
@login_required
def save_phone():
    data  = request.get_json()
    phone = data.get('phone', '').strip()
    import re
    if not re.match(r'^\+91[6-9][0-9]{9}$', phone):
        return jsonify({'error': 'Invalid phone number'}), 400
    session['payment_phone'] = phone
    return jsonify({'success': True})


# ════════════════════════════════════════════════════════
# PAYMENT: CREATE ORDER (monthly ₹29 + yearly ₹499)
# ════════════════════════════════════════════════════════

@app.route('/create-order', methods=['POST'])
@login_required
def create_order():
    data = request.get_json() or {}
    plan = data.get('plan', 'yearly')
    if plan == 'monthly':
        amount      = 2900
        description = 'Pro Membership - 1 Month'
    else:
        amount      = 49900
        description = 'Pro Membership - 1 Year'
    session['payment_plan'] = plan
    keys_present = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
    if not keys_present:
        return jsonify({'order_id': f'mock_order_{uuid.uuid4().hex[:8]}',
                        'amount': amount, 'currency': 'INR', 'mock': True,
                        'description': description})
    try:
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        order  = client.order.create({'amount': amount, 'currency': 'INR',
                                       'payment_capture': 1,
                                       'receipt': f'rcpt_{current_user.id}_{plan}',
                                       'notes': {'plan': plan}})
        return jsonify({'order_id': order['id'], 'amount': amount,
                        'currency': 'INR', 'description': description})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ════════════════════════════════════════════════════════
# PAYMENT: VERIFY AND ACTIVATE PRO
# ════════════════════════════════════════════════════════

@app.route('/api/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    data       = request.get_json()
    order_id   = data.get('razorpay_order_id', '')
    payment_id = data.get('razorpay_payment_id', '')
    signature  = data.get('razorpay_signature', '')
    plan       = data.get('plan', '') or session.get('payment_plan', 'yearly')

    def activate_pro():
        phone = data.get('phone', '') or session.get('payment_phone', '')
        if plan == 'monthly':
            expires_at = datetime.utcnow() + timedelta(days=31)
        else:
            expires_at = datetime.utcnow() + timedelta(days=365)
        update_fields = {
            'is_pro': True, 'pro_plan': plan,
            'pro_activated_at': datetime.utcnow(),
            'pro_expires_at': expires_at,
            'payment_id': payment_id,
        }
        if phone:
            update_fields['phone'] = phone
        session.pop('payment_phone', None)
        session.pop('payment_plan', None)
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': update_fields}
        )

    keys_present = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
    if not keys_present and order_id.startswith('mock_'):
        activate_pro()
        return jsonify({'success': True})
    if not keys_present:
        return jsonify({'success': False, 'error': 'Payment keys not configured'}), 500
    try:
        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode('utf-8'),
            f'{order_id}|{payment_id}'.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(expected, signature):
            activate_pro()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Payment verification failed'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/payment-success')
@login_required
def payment_success():
    return render_template('payment_success.html')



# ════════════════════════════════════════════════════════
# ADMIN
# ════════════════════════════════════════════════════════

@app.route('/admin/scrape', methods=['POST'])
@login_required
def admin_scrape():
    try:
        from scrapers.scheme_scraper import run_scraper
        count = run_scraper(mongo)
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/admin/make-pro', methods=['POST'])
@login_required
def admin_make_pro():
    # SECURITY: Only works when app.debug=True (python run.py locally)
    # On Render/production, debug=False so this route is blocked
    if not app.debug:
        return jsonify({'error': 'Not available in production'}), 403
    mongo.db.users.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$set': {'is_pro': True, 'pro_activated_at': datetime.utcnow()}}
    )
    return jsonify({'success': True, 'message': 'Pro activated!'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)