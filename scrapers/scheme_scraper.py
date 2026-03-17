"""
Government Schemes Scraper - Enhanced Version
Scrapes from myscheme.gov.in API + state portals
Runs every hour via APScheduler
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
import re
from apscheduler.schedulers.background import BackgroundScheduler
from utils import clean_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

CATEGORY_KEYWORDS = {
    'agriculture': ['agriculture', 'crop', 'soil', 'irrigation', 'fertilizer', 'horticulture', 'kisan', 'farming', 'seed', 'harvest'],
    'farmer': ['farmer', 'farm', 'kisan', 'kisaan', 'agrarian', 'cultivator', 'rythu', 'ryot'],
    'healthcare': ['health', 'medical', 'hospital', 'disease', 'medicine', 'ayushman', 'treatment', 'sanitation', 'nutrition', 'aarogya'],
    'women': ['women', 'girl', 'mahila', 'beti', 'maternity', 'child', 'widow', 'gender', 'stree', 'balika'],
    'education': ['education', 'scholarship', 'school', 'college', 'student', 'study', 'vidya', 'siksha', 'fellowship', 'research'],
    'housing': ['housing', 'house', 'home', 'shelter', 'awas', 'pradhan mantri awas', 'grih', 'residence'],
    'employment': ['employment', 'job', 'work', 'livelihood', 'mgnrega', 'rozgar', 'wage', 'labour', 'manrega'],
    'finance': ['loan', 'credit', 'mudra', 'bank', 'finance', 'subsidy', 'fund', 'insurance', 'deposit', 'interest'],
    'social': ['social', 'welfare', 'backward', 'sc', 'st', 'obc', 'dalit', 'tribal', 'minority', 'deprived'],
    'skill': ['skill', 'training', 'vocational', 'apprentice', 'pmkvy', 'kaushal', 'workshop', 'capacity'],
    'msme': ['msme', 'business', 'enterprise', 'startup', 'industry', 'manufacture', 'entrepreneur', 'udyog', 'udyam'],
    'pension': ['pension', 'retirement', 'atal pension', 'jeevan', 'annuity', 'provident', 'superannuation'],
    'disability': ['disability', 'disabled', 'handicap', 'divyangjan', 'specially abled', 'impairment', 'blind', 'deaf'],
    'minority': ['minority', 'muslim', 'christian', 'sikh', 'jain', 'buddhist', 'waqf', 'madrasa'],
    'digital': ['digital', 'internet', 'computer', 'technology', 'e-governance', 'broadband', 'cyber', 'software'],
    'environment': ['environment', 'solar', 'green', 'renewable', 'forest', 'pollution', 'climate', 'energy', 'bio'],
    'tribal': ['tribal', 'adivasi', 'schedule tribe', 'van', 'forest dweller', 'vanvasi'],
    'transport': ['transport', 'road', 'railway', 'vehicle', 'auto', 'bus', 'metro', 'highway'],
    'sports': ['sports', 'youth', 'athlete', 'game', 'fitness', 'stadium', 'tournament', 'khelo'],
}


def detect_category(text):
    text_lower = text.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else 'other'


# MEESEVA-linked scheme keywords (Telangana/AP services)
MEESEVA_KEYWORDS = [
    'meeseva', 'mee seva', 'dharani', 'ts-ipass', 'ap-ipass',
    'encumbrance certificate', 'caste certificate', 'income certificate',
    'residence certificate', 'pattadar passbook', 'land registration',
    'ration card', 'birth certificate', 'death certificate',
    'property tax', 'water connection', 'electricity connection',
    'aarogyasri', 'rythu bharosa', 'kalyana lakshmi', 'shaadi mubarak',
    'aasara pension', 'vahana mitra', 'kanti velugu', 'rythu bandu'
]

ONLINE_APPLY_DOMAINS = [
    'pmkisan.gov.in', 'scholarships.gov.in', 'nrega.nic.in',
    'mudra.org.in', 'startupindia.gov.in', 'myscheme.gov.in',
    'pmaymis.gov.in', 'pmayg.nic.in', 'pmjay.gov.in',
    'nsap.nic.in', 'npscra.nsdl.co.in', 'pmkvyofficial.org',
    'pmfby.gov.in', 'desw.gov.in', 'socialsecurity.mizoram.gov.in',
    'telanganaepass.cgg.gov.in', 'dharani.telangana.gov.in',
    'ysrrythubharosa.ap.gov.in', 'services.india.gov.in',
    'umang.gov.in', 'digilocker.gov.in', 'jansamarth.in'
]


def detect_apply_mode(title, desc, application_url, state=''):
    """Detect how the scheme can be applied for"""
    text = (title + ' ' + desc + ' ' + (state or '')).lower()
    url  = (application_url or '').lower()

    # Check MEESEVA
    if any(kw in text for kw in MEESEVA_KEYWORDS):
        return 'meeseva'
    if 'meeseva' in url or 'mee-seva' in url:
        return 'meeseva'
    if state and state.lower() in ['telangana', 'andhra pradesh']:
        if any(kw in text for kw in ['certificate', 'passbook', 'pension', 'rythu', 'aarogyasri']):
            return 'meeseva'

    # Check online apply
    if any(domain in url for domain in ONLINE_APPLY_DOMAINS):
        return 'online'
    if any(kw in url for kw in ['apply', 'register', 'enroll', 'portal', 'login', 'form']):
        return 'online'
    if any(kw in text for kw in ['apply online', 'online application', 'online registration', 'digital application']):
        return 'online'

    # Default offline/CSC
    return 'offline'


    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:1000]


# ── SCRAPER 1: myscheme.gov.in official API ──────────────────────────────────

def scrape_myscheme(mongo, page_size=100):
    """Scrape from myscheme.gov.in public API - most reliable source"""
    count = 0
    logger.info("🔄 Scraping myscheme.gov.in API...")

    try:
        # Try the v4 API first
        api_url = "https://api.myscheme.gov.in/search/v4/schemes"
        params = {'lang': 'en', 'q': '', 'from': 0, 'size': page_size}
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=60)

        if resp.status_code == 200:
            data = resp.json()
            hits = data.get('data', {}).get('hits', [])
            logger.info(f"myscheme API returned {len(hits)} schemes")

            for item in hits:
                src = item.get('_source', {})
                title = clean_text(src.get('schemeName') or src.get('name', ''))
                if not title or len(title) < 5:
                    continue

                desc = clean_text(src.get('briefDescription') or src.get('description', ''))
                ministry = clean_text(src.get('ministry') or src.get('nodal_ministry', ''))
                beneficiary = clean_text(src.get('targetBeneficiary') or src.get('beneficiaries', ''))
                benefits_raw = src.get('benefits', '')
                benefits = clean_text(benefits_raw if isinstance(benefits_raw, str) else str(benefits_raw))
                eligibility_raw = src.get('eligibility', '')
                eligibility = clean_text(eligibility_raw if isinstance(eligibility_raw, str) else str(eligibility_raw))
                scheme_id = src.get('schemeId') or src.get('id', '')
                source_url = f"https://www.myscheme.gov.in/schemes/{scheme_id}" if scheme_id else ''
                app_url = src.get('schemeUrl') or src.get('applicationUrl', '') or source_url
                state_name = src.get('state', '') or ''
                level = 'state' if state_name and state_name.lower() not in ['', 'central', 'all india'] else 'central'
                category = detect_category(f"{title} {desc} {ministry} {beneficiary}")

                # Extract last updated date
                last_updated = src.get('lastUpdated') or src.get('updatedAt') or src.get('modifiedDate', '')

                scheme_doc = {
                    'title': title,
                    'description': desc,
                    'level': level,
                    'state': state_name if level == 'state' else '',
                    'category': category,
                    'ministry': ministry,
                    'beneficiary': beneficiary,
                    'benefits': benefits,
                    'eligibility': eligibility,
                    'application_url': app_url,
                    'source_url': source_url,
                    'scheme_id': scheme_id,
                    'last_updated': last_updated,
                    'scraped_at': datetime.utcnow(),
                    'is_active': True,
                    'source': 'myscheme.gov.in'
                }

                mongo.db.schemes.update_one(
                    {'title': title, 'level': level},
                    {'$set': scheme_doc},
                    upsert=True
                )
                count += 1

        # Also try paginated scraping for more schemes
        for offset in [100, 200, 300]:
            try:
                params['from'] = offset
                resp2 = requests.get(api_url, params=params, headers=HEADERS, timeout=20)
                if resp2.status_code == 200:
                    hits2 = resp2.json().get('data', {}).get('hits', [])
                    if not hits2:
                        break
                    for item in hits2:
                        src = item.get('_source', {})
                        title = clean_text(src.get('schemeName') or src.get('name', ''))
                        if not title:
                            continue
                        desc = clean_text(src.get('briefDescription', ''))
                        ministry = clean_text(src.get('ministry', ''))
                        beneficiary = clean_text(src.get('targetBeneficiary', ''))
                        scheme_id = src.get('schemeId', '')
                        source_url = f"https://www.myscheme.gov.in/schemes/{scheme_id}" if scheme_id else ''
                        level = 'central'
                        category = detect_category(f"{title} {desc} {ministry}")
                        last_updated = src.get('lastUpdated', '')
                        scheme_doc = {
                            'title': title, 'description': desc, 'level': level,
                            'state': '', 'category': category, 'ministry': ministry,
                            'beneficiary': beneficiary,
                            'benefits': clean_text(str(src.get('benefits', ''))),
                            'eligibility': clean_text(str(src.get('eligibility', ''))),
                            'application_url': source_url, 'source_url': source_url,
                            'scheme_id': scheme_id, 'last_updated': last_updated,
                            'scraped_at': datetime.utcnow(), 'is_active': True,
                            'source': 'myscheme.gov.in'
                        }
                        mongo.db.schemes.update_one(
                            {'title': title, 'level': 'central'},
                            {'$set': scheme_doc}, upsert=True
                        )
                        count += 1
            except Exception:
                break

    except Exception as e:
        logger.error(f"myscheme.gov.in error: {e}")

    logger.info(f"✅ myscheme.gov.in: {count} schemes upserted")
    return count


# ── SCRAPER 2: Individual ministry websites ──────────────────────────────────

MINISTRY_SCHEMES = [
    {
        'url': 'https://pmkisan.gov.in',
        'title': 'PM Kisan Samman Nidhi',
        'category': 'agriculture',
        'ministry': 'Ministry of Agriculture & Farmers Welfare',
        'beneficiary': 'Small and Marginal Farmers',
        'benefits': '₹6,000 per year in 3 installments of ₹2,000 each',
        'eligibility': 'Land-holding farmer families with combined landholding up to 2 hectares',
        'level': 'central',
        'scheme_id': 'pm-kisan'
    },
    {
        'url': 'https://pmfby.gov.in',
        'title': 'Pradhan Mantri Fasal Bima Yojana',
        'category': 'agriculture',
        'ministry': 'Ministry of Agriculture & Farmers Welfare',
        'beneficiary': 'All farmers including sharecroppers and tenant farmers',
        'benefits': 'Crop insurance coverage against natural calamities, pests & diseases',
        'eligibility': 'All farmers growing notified crops in notified areas',
        'level': 'central',
        'scheme_id': 'pmfby'
    },
    {
        'url': 'https://pmjay.gov.in',
        'title': 'Ayushman Bharat PM-JAY',
        'category': 'healthcare',
        'ministry': 'Ministry of Health & Family Welfare',
        'beneficiary': 'Bottom 40% of Indian population (SECC database)',
        'benefits': 'Health coverage of ₹5 lakh per family per year for secondary & tertiary hospitalization',
        'eligibility': 'Families listed in SECC 2011 database, no cap on family size',
        'level': 'central',
        'scheme_id': 'ayushman-bharat'
    },
    {
        'url': 'https://pmaymis.gov.in',
        'title': 'Pradhan Mantri Awas Yojana – Urban',
        'category': 'housing',
        'ministry': 'Ministry of Housing & Urban Affairs',
        'beneficiary': 'EWS/LIG/MIG urban families without pucca house',
        'benefits': 'Interest subsidy up to ₹2.67 lakh on home loans',
        'eligibility': 'EWS (income < ₹3L), LIG (₹3-6L), MIG-I (₹6-12L), MIG-II (₹12-18L)',
        'level': 'central',
        'scheme_id': 'pmay-urban'
    },
    {
        'url': 'https://pmayg.nic.in',
        'title': 'PM Awas Yojana – Gramin',
        'category': 'housing',
        'ministry': 'Ministry of Rural Development',
        'beneficiary': 'Homeless/kutcha house rural BPL families',
        'benefits': '₹1.20 lakh (plain areas) / ₹1.30 lakh (hilly/difficult areas) per unit',
        'eligibility': 'Houseless families & those with kutcha/dilapidated house in SECC list',
        'level': 'central',
        'scheme_id': 'pmay-gramin'
    },
    {
        'url': 'https://nrega.nic.in',
        'title': 'MGNREGA',
        'category': 'employment',
        'ministry': 'Ministry of Rural Development',
        'beneficiary': 'Rural households willing to do unskilled manual work',
        'benefits': '100 days of guaranteed wage employment per year at statutory minimum wage',
        'eligibility': 'Adult members of any rural household willing to do unskilled manual work',
        'level': 'central',
        'scheme_id': 'mgnrega'
    },
    {
        'url': 'https://mudra.org.in',
        'title': 'PM Mudra Yojana',
        'category': 'finance',
        'ministry': 'Ministry of Finance',
        'beneficiary': 'Non-corporate non-farm micro/small enterprises',
        'benefits': 'Shishu: up to ₹50,000 | Kishore: ₹50K-5L | Tarun: ₹5L-10L (no collateral)',
        'eligibility': 'Non-farm income generating micro enterprises, individuals, proprietorships, partnerships',
        'level': 'central',
        'scheme_id': 'mudra'
    },
    {
        'url': 'https://scholarships.gov.in',
        'title': 'National Scholarship Portal',
        'category': 'education',
        'ministry': 'Ministry of Education',
        'beneficiary': 'SC/ST/OBC/Minority/Meritorious students',
        'benefits': 'Pre-matric to post-doctoral scholarships from ₹1,000 to ₹20,000/year',
        'eligibility': 'Students from SC/ST/OBC/Minority with family income below threshold',
        'level': 'central',
        'scheme_id': 'nsp'
    },
    {
        'url': 'https://npscra.nsdl.co.in',
        'title': 'Atal Pension Yojana',
        'category': 'pension',
        'ministry': 'Ministry of Finance / PFRDA',
        'beneficiary': 'Unorganized sector workers aged 18-40',
        'benefits': 'Guaranteed pension of ₹1,000–₹5,000/month after age 60',
        'eligibility': 'Indian citizens aged 18-40 with savings bank account, not income tax payer',
        'level': 'central',
        'scheme_id': 'apy'
    },
    {
        'url': 'https://pmkvyofficial.org',
        'title': 'Pradhan Mantri Kaushal Vikas Yojana (PMKVY)',
        'category': 'skill',
        'ministry': 'Ministry of Skill Development & Entrepreneurship',
        'beneficiary': 'Indian youth (15-45 years), school/college dropouts',
        'benefits': 'Free skill training + ₹8,000 monetary reward + placement support',
        'eligibility': 'Indian nationals aged 15-45, school/college dropout or seeking re-skilling',
        'level': 'central',
        'scheme_id': 'pmkvy'
    },
    {
        'url': 'https://startupindia.gov.in',
        'title': 'Startup India Initiative',
        'category': 'msme',
        'ministry': 'Ministry of Commerce & Industry – DPIIT',
        'beneficiary': 'Innovative startups incorporated < 10 years',
        'benefits': 'Tax exemptions (3 years), funding access, IPR support, 80% rebate on patent fees',
        'eligibility': 'Entities < 10 years old, turnover < ₹100 crore/year, working on innovation',
        'level': 'central',
        'scheme_id': 'startup-india'
    },
    {
        'url': 'https://wcd.nic.in',
        'title': 'Beti Bachao Beti Padhao',
        'category': 'women',
        'ministry': 'Ministry of Women & Child Development',
        'beneficiary': 'Girl child and their families',
        'benefits': 'Financial assistance, awareness campaigns, incentives for girl education',
        'eligibility': 'All girl children; priority districts with low child sex ratio',
        'level': 'central',
        'scheme_id': 'bbbp'
    },
    {
        'url': 'https://nhm.gov.in',
        'title': 'Janani Suraksha Yojana',
        'category': 'women',
        'ministry': 'Ministry of Health & Family Welfare',
        'beneficiary': 'Pregnant women from BPL/SC/ST categories',
        'benefits': '₹1,400 (rural) / ₹1,000 (urban) cash assistance for institutional delivery',
        'eligibility': 'All pregnant women from BPL; no age/parity limit in LPS states',
        'level': 'central',
        'scheme_id': 'jsy'
    },
    {
        'url': 'https://nsap.nic.in',
        'title': 'National Social Assistance Programme (NSAP)',
        'category': 'social',
        'ministry': 'Ministry of Rural Development',
        'beneficiary': 'Aged, widows and disabled BPL persons',
        'benefits': '₹200-₹500/month pension depending on age and category',
        'eligibility': 'BPL households with aged (60+), widows (40-79), disabled persons',
        'level': 'central',
        'scheme_id': 'nsap'
    },
    {
        'url': 'https://pmgdisha.in',
        'title': 'PM Gramin Digital Saksharta Abhiyan (PMGDISHA)',
        'category': 'digital',
        'ministry': 'Ministry of Electronics & Information Technology',
        'beneficiary': 'Digitally illiterate rural household members',
        'benefits': 'Free digital literacy training covering internet, mobile & computer basics',
        'eligibility': 'One non-literate/digitally illiterate member per eligible rural household',
        'level': 'central',
        'scheme_id': 'pmgdisha'
    },
    {
        'url': 'https://www.nabard.org',
        'title': 'Kisan Credit Card (KCC)',
        'category': 'farmer',
        'ministry': 'Ministry of Agriculture & Farmers Welfare / NABARD',
        'beneficiary': 'All farmers, sharecroppers, oral lessees and SHGs',
        'benefits': 'Credit up to ₹3 lakh at 4% interest per annum (with 2% GoI subvention)',
        'eligibility': 'All farmers including sharecroppers, oral lessees, self-help groups and JLGs',
        'level': 'central',
        'scheme_id': 'kcc'
    },
]

# State scheme definitions
STATE_SCHEMES = [
    # Telangana
    {
        'title': 'Rythu Bandhu',
        'description': 'Investment support scheme for all land-owning farmers in Telangana. Provides financial assistance for agricultural inputs at the beginning of each crop season.',
        'level': 'state', 'state': 'Telangana', 'category': 'agriculture',
        'ministry': 'Telangana Agriculture & Cooperation Department',
        'beneficiary': 'All land-owning farmers registered in Dharani portal',
        'benefits': '₹10,000 per acre per year (₹5,000/season × 2 seasons)',
        'eligibility': 'Land-owning farmers in Telangana with pattadar passbook; sharecroppers not covered',
        'application_url': 'https://dharani.telangana.gov.in',
        'source_url': 'https://rythubandhu.telangana.gov.in',
        'scheme_id': 'rythu-bandhu-ts'
    },
    {
        'title': 'Aarogyasri Health Care Trust (Telangana)',
        'description': 'Comprehensive health insurance scheme for BPL families in Telangana providing cashless treatment for over 2,400 medical procedures at empanelled hospitals.',
        'level': 'state', 'state': 'Telangana', 'category': 'healthcare',
        'ministry': 'Telangana Health, Medical & Family Welfare Department',
        'beneficiary': 'White ration card (BPL) families in Telangana',
        'benefits': 'Cashless treatment up to ₹5 lakh/year; covers 2,400+ procedures including surgeries',
        'eligibility': 'Families with white ration card issued by Telangana Civil Supplies Department',
        'application_url': 'https://aarogyasri.telangana.gov.in',
        'source_url': 'https://aarogyasri.telangana.gov.in',
        'scheme_id': 'aarogyasri-ts'
    },
    {
        'title': 'Kalyana Lakshmi / Shaadi Mubarak',
        'description': 'Financial assistance for marriage of girls belonging to SC/ST/BC/Minority communities in Telangana to prevent child marriages and support families.',
        'level': 'state', 'state': 'Telangana', 'category': 'women',
        'ministry': 'Telangana SC Development, BC Welfare & Minority Welfare Departments',
        'beneficiary': 'Brides from SC/ST/BC/Minority communities',
        'benefits': '₹1,00,116 one-time financial assistance transferred to bride\'s bank account',
        'eligibility': 'Bride from SC/ST/BC/Minority; family income < ₹2 lakh/year; bride age ≥ 18 years',
        'application_url': 'https://telanganaepass.cgg.gov.in',
        'source_url': 'https://telanganaepass.cgg.gov.in',
        'scheme_id': 'kalyana-lakshmi-ts'
    },
    {
        'title': 'Telangana 2BHK Housing Scheme',
        'description': 'Double bedroom houses scheme providing free pucca 2BHK houses to homeless poor families in Telangana urban and rural areas.',
        'level': 'state', 'state': 'Telangana', 'category': 'housing',
        'ministry': 'Telangana Housing Department / CDMA',
        'beneficiary': 'Homeless poor families in Telangana',
        'benefits': 'Free 2-BHK house (560 sq ft) with all basic amenities',
        'eligibility': 'Homeless families in Telangana with no house in their name; income < ₹3 lakh/year',
        'application_url': 'https://cdma.telangana.gov.in',
        'source_url': 'https://telanganahousing.gov.in',
        'scheme_id': '2bhk-ts'
    },
    {
        'title': 'TS-iPASS (Industrial Policy)',
        'description': 'Telangana State Industrial Project Approval and Self-Certification System — single window clearance for businesses to set up industries in Telangana.',
        'level': 'state', 'state': 'Telangana', 'category': 'msme',
        'ministry': 'Telangana Industries & Commerce Department',
        'beneficiary': 'Entrepreneurs and industries of all scales setting up in Telangana',
        'benefits': 'Single-window approvals, land subsidies, power tariff concessions, tax incentives',
        'eligibility': 'Any entrepreneur or company planning to establish industry/business in Telangana',
        'application_url': 'https://ipass.telangana.gov.in',
        'source_url': 'https://ipass.telangana.gov.in',
        'scheme_id': 'tsipass'
    },
    {
        'title': 'Telangana ePASS Scholarship',
        'description': 'Scholarships for students from SC, ST, BC, EBC and Minority communities studying in Telangana colleges, covering tuition fee and maintenance allowance.',
        'level': 'state', 'state': 'Telangana', 'category': 'education',
        'ministry': 'Telangana BC Welfare / SC Dev / Tribal Welfare / Minority Welfare Departments',
        'beneficiary': 'SC/ST/BC/EBC/Minority students in Telangana',
        'benefits': 'Full tuition fee reimbursement + maintenance allowance (₹7,000-₹10,000/year)',
        'eligibility': 'SC/ST/BC/Minority student; family income < ₹2.5 lakh (BC) or < ₹2 lakh (SC/ST)',
        'application_url': 'https://telanganaepass.cgg.gov.in',
        'source_url': 'https://telanganaepass.cgg.gov.in',
        'scheme_id': 'epass-ts'
    },
    # Andhra Pradesh
    {
        'title': 'YSR Rythu Bharosa',
        'description': 'Investment support scheme for farmers in Andhra Pradesh providing financial assistance for agricultural inputs at beginning of Kharif and Rabi seasons.',
        'level': 'state', 'state': 'Andhra Pradesh', 'category': 'agriculture',
        'ministry': 'Andhra Pradesh Agriculture & Cooperation Department',
        'beneficiary': 'All farmer families (land-owning and tenant farmers) in AP',
        'benefits': '₹13,500 per year per farmer family (includes PM Kisan ₹6,000 + state share ₹7,500)',
        'eligibility': 'Farmer families in AP; both land-owning and tenant farmers eligible',
        'application_url': 'https://ysrrythubharosa.ap.gov.in',
        'source_url': 'https://ysrrythubharosa.ap.gov.in',
        'scheme_id': 'ysr-rythu-bharosa'
    },
    {
        'title': 'YSR Aarogyasri',
        'description': 'Universal health coverage scheme in Andhra Pradesh providing cashless treatment for poor families at empanelled government and private hospitals.',
        'level': 'state', 'state': 'Andhra Pradesh', 'category': 'healthcare',
        'ministry': 'Andhra Pradesh Health, Medical & Family Welfare Department',
        'beneficiary': 'All families with annual income below ₹5 lakh in AP',
        'benefits': 'Cashless treatment up to ₹5 lakh/year; covers 2,700+ procedures',
        'eligibility': 'AP resident families with Aadhaar-linked ration card or income certificate',
        'application_url': 'https://ysraarogyasri.ap.gov.in',
        'source_url': 'https://ysraarogyasri.ap.gov.in',
        'scheme_id': 'ysr-aarogyasri'
    },
    # Maharashtra
    {
        'title': 'Mahatma Jyotirao Phule Jan Arogya Yojana',
        'description': 'Health insurance scheme for BPL and marginalized families in Maharashtra providing cashless treatment at government and private hospitals.',
        'level': 'state', 'state': 'Maharashtra', 'category': 'healthcare',
        'ministry': 'Maharashtra Health Department',
        'beneficiary': 'Yellow/Orange/Antyodaya ration card holders in Maharashtra',
        'benefits': 'Cashless hospitalization up to ₹1.5 lakh/year; 971 procedures covered',
        'eligibility': 'Families with Yellow/Orange/Antyodaya/Annapurna ration cards in Maharashtra',
        'application_url': 'https://www.jeevandayee.gov.in',
        'source_url': 'https://www.jeevandayee.gov.in',
        'scheme_id': 'mjpjay-mh'
    },
    {
        'title': 'Mahaswarnim Scheme (Maharashtra)',
        'description': 'Financial assistance and subsidy scheme for MSME entrepreneurs and artisans from SC/ST/OBC communities in Maharashtra.',
        'level': 'state', 'state': 'Maharashtra', 'category': 'msme',
        'ministry': 'Maharashtra Social Justice & Special Assistance Department',
        'beneficiary': 'SC/ST/OBC entrepreneurs and artisans in Maharashtra',
        'benefits': 'Loans up to ₹50 lakh with subsidies; margin money assistance',
        'eligibility': 'SC/ST/OBC entrepreneurs in Maharashtra; business plan required',
        'application_url': 'https://sjsa.maharashtra.gov.in',
        'source_url': 'https://sjsa.maharashtra.gov.in',
        'scheme_id': 'mahaswarnim-mh'
    },
    # Karnataka
    {
        'title': 'Rajiv Gandhi Scheme for Empowerment of Adolescent Girls (Karnataka)',
        'description': 'Multi-convergence programme for adolescent girls in Karnataka covering nutrition, health, education and social development.',
        'level': 'state', 'state': 'Karnataka', 'category': 'women',
        'ministry': 'Karnataka Women & Child Development Department',
        'beneficiary': 'Adolescent girls aged 11-18 years in Karnataka',
        'benefits': 'Nutrition support, health checkups, life skills education, vocational training',
        'eligibility': 'Adolescent girls (11-18 years) in selected blocks of Karnataka',
        'application_url': 'https://wcd.kar.nic.in',
        'source_url': 'https://wcd.kar.nic.in',
        'scheme_id': 'rgseag-ka'
    },
    {
        'title': 'Gruha Lakshmi (Karnataka)',
        'description': 'Monthly financial assistance to the woman head of the family in Karnataka as part of the state\'s guarantee scheme.',
        'level': 'state', 'state': 'Karnataka', 'category': 'women',
        'ministry': 'Karnataka Women & Child Development Department',
        'beneficiary': 'Woman head of family with ration card in Karnataka',
        'benefits': '₹2,000 per month directly to woman head of household',
        'eligibility': 'Woman head of household with Karnataka ration card (BPL/APL); not government employee',
        'application_url': 'https://sevasindhu.karnataka.gov.in',
        'source_url': 'https://sevasindhu.karnataka.gov.in',
        'scheme_id': 'gruha-lakshmi-ka'
    },
    # Tamil Nadu
    {
        'title': 'Kalaignar Magalir Urimai Thittam (Tamil Nadu)',
        'description': 'Monthly financial assistance of ₹1,000 to women heads of families in Tamil Nadu to support their financial independence.',
        'level': 'state', 'state': 'Tamil Nadu', 'category': 'women',
        'ministry': 'Tamil Nadu Social Welfare & Women Empowerment Department',
        'beneficiary': 'Women heads of families in Tamil Nadu',
        'benefits': '₹1,000 per month per family',
        'eligibility': 'Women head of household with TN ration card; income < ₹2.5 lakh/year; age 21-60',
        'application_url': 'https://magalivazhurimai.tn.gov.in',
        'source_url': 'https://magalivazhurimai.tn.gov.in',
        'scheme_id': 'kalaignar-tn'
    },
    {
        'title': 'Chief Minister\'s Comprehensive Health Insurance Scheme (TN)',
        'description': 'Health insurance scheme covering poor families in Tamil Nadu for specialized treatments and surgeries at government and private hospitals.',
        'level': 'state', 'state': 'Tamil Nadu', 'category': 'healthcare',
        'ministry': 'Tamil Nadu Health & Family Welfare Department',
        'beneficiary': 'Families with annual income < ₹72,000 in Tamil Nadu',
        'benefits': '₹5 lakh health coverage/year; 1,027 procedures; ₹25 lakh for major ailments',
        'eligibility': 'TN residents with family income < ₹72,000/year and valid ration card',
        'application_url': 'https://www.cmchistn.com',
        'source_url': 'https://www.cmchistn.com',
        'scheme_id': 'cmchis-tn'
    },
]


def upsert_scheme(mongo, doc):
    """Safely upsert a scheme document"""
    if not doc.get('last_updated'):
        doc['last_updated'] = ''
    if not doc.get('scraped_at'):
        doc['scraped_at'] = datetime.utcnow()
    if not doc.get('is_active'):
        doc['is_active'] = True
    if not doc.get('source'):
        doc['source'] = 'official'
    # Auto-detect apply_mode if not set
    if not doc.get('apply_mode'):
        doc['apply_mode'] = detect_apply_mode(
            doc.get('title', ''),
            doc.get('description', ''),
            doc.get('application_url', ''),
            doc.get('state', '')
        )

    filter_q = {'title': doc['title'], 'level': doc.get('level', 'central')}
    if doc.get('state'):
        filter_q['state'] = doc['state']

    mongo.db.schemes.update_one(filter_q, {'$set': doc}, upsert=True)


def scrape_ministry_websites(mongo):
    """Fetch detailed descriptions from ministry websites for known schemes"""
    count = 0
    logger.info("🔄 Updating ministry scheme details...")

    for scheme in MINISTRY_SCHEMES:
        try:
            resp = requests.get(scheme['url'], headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                # Try to get meta description or first paragraph
                meta_desc = soup.find('meta', attrs={'name': 'description'})
                page_desc = meta_desc.get('content', '') if meta_desc else ''
                if not page_desc:
                    p_tag = soup.find('p')
                    page_desc = p_tag.get_text(strip=True)[:500] if p_tag else ''

                desc = page_desc if len(page_desc) > 50 else f"Official scheme portal: {scheme['title']}"
            else:
                desc = f"Official government scheme. Visit {scheme['url']} for details."
        except Exception:
            desc = f"Official government scheme. Visit {scheme['url']} for details."

        scheme_doc = {
            'title': scheme['title'],
            'description': desc,
            'level': scheme.get('level', 'central'),
            'state': scheme.get('state', ''),
            'category': scheme['category'],
            'ministry': scheme['ministry'],
            'beneficiary': scheme['beneficiary'],
            'benefits': scheme['benefits'],
            'eligibility': scheme['eligibility'],
            'application_url': scheme['url'],
            'source_url': scheme['url'],
            'scheme_id': scheme.get('scheme_id', ''),
            'last_updated': datetime.utcnow().strftime('%Y-%m-%d'),
            'scraped_at': datetime.utcnow(),
            'is_active': True,
            'source': 'ministry_official'
        }
        upsert_scheme(mongo, scheme_doc)
        count += 1

    logger.info(f"✅ Ministry schemes: {count} upserted")
    return count


def scrape_state_schemes(mongo):
    """Upsert all defined state schemes"""
    count = 0
    logger.info("🔄 Updating state schemes...")
    for scheme in STATE_SCHEMES:
        scheme_doc = dict(scheme)
        scheme_doc['last_updated'] = datetime.utcnow().strftime('%Y-%m-%d')
        scheme_doc['scraped_at'] = datetime.utcnow()
        scheme_doc['is_active'] = True
        scheme_doc['source'] = 'state_official'
        upsert_scheme(mongo, scheme_doc)
        count += 1
    logger.info(f"✅ State schemes: {count} upserted")
    return count


def scrape_myscheme_deep(mongo):
    """Deep scrape myscheme.gov.in — paginate through ALL schemes (up to 5000+)"""
    count = 0
    logger.info("🔄 Deep scraping myscheme.gov.in for 5000+ schemes...")
    api_url = "https://api.myscheme.gov.in/search/v4/schemes"

    # Also try state-specific queries
    state_queries = [
        '', 'Andhra Pradesh', 'Telangana', 'Maharashtra', 'Uttar Pradesh',
        'Bihar', 'Rajasthan', 'Madhya Pradesh', 'Karnataka', 'Tamil Nadu',
        'West Bengal', 'Gujarat', 'Kerala', 'Odisha', 'Jharkhand',
        'Chhattisgarh', 'Haryana', 'Punjab', 'Assam', 'Delhi',
        'Himachal Pradesh', 'Uttarakhand', 'Goa', 'Tripura', 'Manipur',
        'Meghalaya', 'Nagaland', 'Mizoram', 'Arunachal Pradesh', 'Sikkim',
        'Jammu and Kashmir', 'Ladakh', 'Chandigarh', 'Puducherry',
        'Andaman and Nicobar Islands', 'Lakshadweep', 'Dadra and Nagar Haveli'
    ]

    category_queries = [
        'agriculture', 'health', 'education', 'housing', 'employment',
        'women', 'farmer', 'skill', 'pension', 'disability', 'tribal',
        'minority', 'digital', 'finance', 'social welfare', 'sports',
        'environment', 'transport', 'business', 'startup'
    ]

    all_queries = [(q, 'state') for q in state_queries] + [(q, 'cat') for q in category_queries]

    for query, qtype in all_queries:
        try:
            for offset in range(0, 500, 100):
                params = {'lang': 'en', 'q': query, 'from': offset, 'size': 100}
                resp = requests.get(api_url, params=params, headers=HEADERS, timeout=25)
                if resp.status_code != 200:
                    break
                hits = resp.json().get('data', {}).get('hits', [])
                if not hits:
                    break
                for item in hits:
                    src = item.get('_source', {})
                    title = clean_text(src.get('schemeName') or src.get('name', ''))
                    if not title or len(title) < 5:
                        continue
                    desc        = clean_text(src.get('briefDescription') or src.get('description', ''))
                    ministry    = clean_text(src.get('ministry') or src.get('nodal_ministry', ''))
                    beneficiary = clean_text(src.get('targetBeneficiary') or src.get('beneficiaries', ''))
                    benefits    = clean_text(str(src.get('benefits', '')))
                    eligibility = clean_text(str(src.get('eligibility', '')))
                    scheme_id   = src.get('schemeId') or src.get('id', '')
                    source_url  = f"https://www.myscheme.gov.in/schemes/{scheme_id}" if scheme_id else ''
                    app_url     = src.get('schemeUrl') or src.get('applicationUrl', '') or source_url
                    state_name  = src.get('state', '') or ''
                    level       = 'state' if state_name and state_name.lower() not in ['', 'central', 'all india', 'pan india'] else 'central'
                    category    = detect_category(f"{title} {desc} {ministry} {beneficiary}")
                    last_upd    = src.get('lastUpdated') or src.get('updatedAt', '')
                    apply_mode  = detect_apply_mode(title, desc, app_url, state_name)

                    scheme_doc = {
                        'title': title, 'description': desc, 'level': level,
                        'state': state_name if level == 'state' else '',
                        'category': category, 'ministry': ministry,
                        'beneficiary': beneficiary, 'benefits': benefits,
                        'eligibility': eligibility, 'application_url': app_url,
                        'source_url': source_url, 'scheme_id': scheme_id,
                        'last_updated': last_upd, 'scraped_at': datetime.utcnow(),
                        'is_active': True, 'source': 'myscheme.gov.in',
                        'apply_mode': apply_mode
                    }
                    upsert_scheme(mongo, scheme_doc)
                    count += 1
        except Exception as e:
            logger.warning(f"myscheme deep query '{query}': {e}")
            continue

    logger.info(f"✅ myscheme deep scrape: {count} schemes")
    return count


def scrape_india_gov_api(mongo):
    """Scrape schemes from India.gov.in open data APIs"""
    count = 0
    logger.info("🔄 Scraping India.gov.in APIs...")

    endpoints = [
        'https://data.gov.in/api/datastore/resource.json?resource_id=6176c355-70e1-4a9e-8dcc-c2c0ec99b059&limit=500',
        'https://data.gov.in/api/datastore/resource.json?resource_id=6d24c0ee-7b8b-4a3b-be52-fb0e6a4cab20&limit=500',
    ]

    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue
            records = resp.json().get('records', [])
            for rec in records:
                title = clean_text(rec.get('scheme_name') or rec.get('name') or rec.get('title', ''))
                if not title or len(title) < 5:
                    continue
                desc       = clean_text(rec.get('description') or rec.get('details', ''))
                ministry   = clean_text(rec.get('ministry') or rec.get('department', ''))
                state_name = clean_text(rec.get('state', ''))
                level      = 'state' if state_name and state_name.lower() not in ['central', ''] else 'central'
                app_url    = rec.get('apply_url') or rec.get('url') or rec.get('link', '')
                category   = detect_category(f"{title} {desc} {ministry}")
                apply_mode = detect_apply_mode(title, desc, app_url, state_name)

                scheme_doc = {
                    'title': title, 'description': desc, 'level': level,
                    'state': state_name, 'category': category, 'ministry': ministry,
                    'beneficiary': clean_text(rec.get('beneficiary', '')),
                    'benefits': clean_text(rec.get('benefits', '')),
                    'eligibility': clean_text(rec.get('eligibility', '')),
                    'application_url': app_url, 'source_url': app_url,
                    'scheme_id': '', 'last_updated': '', 'scraped_at': datetime.utcnow(),
                    'is_active': True, 'source': 'data.gov.in', 'apply_mode': apply_mode
                }
                upsert_scheme(mongo, scheme_doc)
                count += 1
        except Exception as e:
            logger.warning(f"data.gov.in error: {e}")

    logger.info(f"✅ India.gov.in APIs: {count} schemes")
    return count


# Comprehensive hardcoded schemes for all states — ensures 5000+ in DB
# These are real schemes from official sources
EXPANDED_SCHEMES = [
    # ── TELANGANA ─────────────────────────────────────────────────────────────
    {'title': 'Rythu Bandhu', 'category': 'farmer', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Agriculture Dept, Telangana', 'beneficiary': 'All farmers with land records',
     'benefits': '₹5,000 per acre per season (₹10,000/acre/year) investment support',
     'eligibility': 'Farmers with Pattadar Passbook/land records in Telangana',
     'application_url': 'https://rythubandhu.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Aarogyasri Health Scheme', 'category': 'healthcare', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Health Dept, Telangana', 'beneficiary': 'BPL families with white ration card',
     'benefits': 'Free treatment up to ₹5 lakh per year at empanelled hospitals',
     'eligibility': 'White ration card holders in Telangana',
     'application_url': 'https://aarogyasri.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Kalyana Lakshmi / Shaadi Mubarak', 'category': 'women', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Social Welfare Dept, Telangana', 'beneficiary': 'SC/ST/BC/Minority brides',
     'benefits': '₹1,00,116 financial assistance at marriage for eligible communities',
     'eligibility': 'Brides from SC/ST/BC/Minority families below poverty line',
     'application_url': 'https://kalyanalakshmi.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Aasara Pension', 'category': 'pension', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Social Welfare, Telangana', 'beneficiary': 'Old age, widows, disabled, toddy tappers',
     'benefits': '₹2,016/month pension for eligible beneficiaries',
     'eligibility': 'BPL families — elderly (60+), widows, disabled, HIV, TSDF beneficiaries',
     'application_url': 'https://mepma.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'KCR Kit', 'category': 'women', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Health Dept, Telangana', 'beneficiary': 'Pregnant women',
     'benefits': '16 essential items kit + ₹12,000 cash incentive for institutional delivery',
     'eligibility': 'All pregnant women delivering at government hospitals in Telangana',
     'application_url': 'https://nhm.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Vahana Mitra', 'category': 'employment', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Transport Dept, Telangana', 'beneficiary': 'Auto/taxi/RTC drivers',
     'benefits': '₹10,000/year ex-gratia to registered auto/taxi drivers',
     'eligibility': 'Commercial vehicle drivers registered in Telangana',
     'application_url': 'https://transport.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Kanti Velugu', 'category': 'healthcare', 'level': 'state', 'state': 'Telangana',
     'ministry': 'Health Dept, Telangana', 'beneficiary': 'All Telangana residents',
     'benefits': 'Free eye examination + free spectacles to those who need them',
     'eligibility': 'All residents of Telangana state',
     'application_url': 'https://kantivelugu.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Dalit Bandhu', 'category': 'social', 'level': 'state', 'state': 'Telangana',
     'ministry': 'SC Development Dept, Telangana', 'beneficiary': 'SC families',
     'benefits': '₹10 lakh per SC household for taking up any enterprise/business',
     'eligibility': 'One member per SC family in Telangana',
     'application_url': 'https://dalitbandhu.telangana.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'TS ePass Scholarship', 'category': 'education', 'level': 'state', 'state': 'Telangana',
     'ministry': 'BC Welfare, Telangana', 'beneficiary': 'SC/ST/BC/EBC/Minority students',
     'benefits': 'Full tuition fee reimbursement + maintenance allowance for higher education',
     'eligibility': 'SC/ST/BC/EBC/Minority students in recognized institutions, family income < ₹2L',
     'application_url': 'https://telanganaepass.cgg.gov.in', 'apply_mode': 'online'},
    {'title': 'TSRTC Free Bus Pass — Students', 'category': 'education', 'level': 'state', 'state': 'Telangana',
     'ministry': 'TSRTC', 'beneficiary': 'Students, disabled, journalists',
     'benefits': 'Free/discounted TSRTC bus travel for eligible categories',
     'eligibility': 'Students with valid ID, disabled persons with certificate',
     'application_url': 'https://tsrtc.telangana.gov.in', 'apply_mode': 'meeseva'},
    # ── ANDHRA PRADESH ────────────────────────────────────────────────────────
    {'title': 'YSR Rythu Bharosa', 'category': 'farmer', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Agriculture Dept, AP', 'beneficiary': 'All farmers in Andhra Pradesh',
     'benefits': '₹13,500/year investment support per farmer family',
     'eligibility': 'All farmers in AP with agricultural land',
     'application_url': 'https://ysrrythubharosa.ap.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'YSR Aarogyasri', 'category': 'healthcare', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Health Dept, AP', 'beneficiary': 'AP residents with YSR Health Card',
     'benefits': 'Free treatment up to ₹5 lakh for 2,440+ procedures at empanelled hospitals',
     'eligibility': 'Families enrolled in YSR Health Card scheme',
     'application_url': 'https://ysraarogyasri.ap.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'AP Amma Vodi', 'category': 'education', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'School Education Dept, AP', 'beneficiary': 'Mothers of school-going children',
     'benefits': '₹15,000/year financial assistance to mothers who send children to school',
     'eligibility': 'Mothers of children studying in AP government schools (Class 1–12)',
     'application_url': 'https://ammavodi.ap.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'YSR Pension Kanuka', 'category': 'pension', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Social Welfare, AP', 'beneficiary': 'Elderly, widows, disabled, weavers',
     'benefits': '₹2,750/month pension for old age; ₹3,000 for disabled; varies by category',
     'eligibility': 'Beneficiaries registered under AP welfare pension schemes',
     'application_url': 'https://spap.ap.gov.in', 'apply_mode': 'meeseva'},
    {'title': 'Jagananna Vidya Deevena', 'category': 'education', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Higher Education Dept, AP', 'beneficiary': 'Students in higher education',
     'benefits': '100% reimbursement of tuition fee for degree/polytechnic/ITI courses',
     'eligibility': 'AP students in government/aided/private colleges, family income < ₹2.5L',
     'application_url': 'https://jaganannavidyadeevena.ap.gov.in', 'apply_mode': 'online'},
    {'title': 'Jagananna Vasathi Deevena', 'category': 'education', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Higher Education Dept, AP', 'beneficiary': 'Hostel students',
     'benefits': '₹10,000–₹20,000/year for hostel/mess expenses for higher education students',
     'eligibility': 'Students staying in hostels for higher education in AP',
     'application_url': 'https://jvd.ap.gov.in', 'apply_mode': 'online'},
    {'title': 'NAVASAKAM — AP Skill Development', 'category': 'skill', 'level': 'state', 'state': 'Andhra Pradesh',
     'ministry': 'Skill Dev Dept, AP', 'beneficiary': 'Unemployed youth aged 18–35',
     'benefits': 'Free skill training + ₹1,000/month stipend + placement assistance',
     'eligibility': 'Unemployed AP youth aged 18–35 with minimum 8th class education',
     'application_url': 'https://apssdc.in', 'apply_mode': 'online'},
    # ── MAHARASHTRA ───────────────────────────────────────────────────────────
    {'title': 'Mahatma Jyotirao Phule Jan Arogya Yojana', 'category': 'healthcare', 'level': 'state', 'state': 'Maharashtra',
     'ministry': 'Health Dept, Maharashtra', 'beneficiary': 'BPL/Yellow/Orange/White ration card holders',
     'benefits': 'Free treatment up to ₹1.5 lakh for 971+ diseases at empanelled hospitals',
     'eligibility': 'Holders of Yellow/Orange/White ration cards in Maharashtra',
     'application_url': 'https://www.jeevandayee.gov.in', 'apply_mode': 'offline'},
    {'title': 'Shiv Bhojan Thali', 'category': 'social', 'level': 'state', 'state': 'Maharashtra',
     'ministry': 'Food & Civil Supplies, Maharashtra', 'beneficiary': 'General public, poor workers',
     'benefits': 'Nutritious meal at ₹5 per plate at government-approved Shiv Bhojan centers',
     'eligibility': 'Any person in need, especially daily wage workers',
     'application_url': 'https://mahafood.gov.in', 'apply_mode': 'offline'},
    {'title': 'Maharashtra Farmer Loan Waiver', 'category': 'farmer', 'level': 'state', 'state': 'Maharashtra',
     'ministry': 'Agriculture Dept, Maharashtra', 'beneficiary': 'Distressed farmers',
     'benefits': 'Loan waiver up to ₹2 lakh for eligible farmers',
     'eligibility': 'Small/marginal farmers with outstanding crop loans',
     'application_url': 'https://krishi.maharashtra.gov.in', 'apply_mode': 'offline'},
    # ── KARNATAKA ─────────────────────────────────────────────────────────────
    {'title': 'Karnataka Gruha Jyoti', 'category': 'social', 'level': 'state', 'state': 'Karnataka',
     'ministry': 'Energy Dept, Karnataka', 'beneficiary': 'Domestic electricity consumers',
     'benefits': 'Free 200 units of electricity per month for domestic consumers',
     'eligibility': 'Karnataka residents with domestic electricity connection',
     'application_url': 'https://bescom.karnataka.gov.in', 'apply_mode': 'online'},
    {'title': 'Karnataka Anna Bhagya', 'category': 'social', 'level': 'state', 'state': 'Karnataka',
     'ministry': 'Food Dept, Karnataka', 'beneficiary': 'BPL ration card holders',
     'benefits': '10 kg free rice per month per BPL family member',
     'eligibility': 'BPL families with valid ration card in Karnataka',
     'application_url': 'https://ahara.kar.nic.in', 'apply_mode': 'offline'},
    {'title': 'Seva Sindhu — Karnataka', 'category': 'social', 'level': 'state', 'state': 'Karnataka',
     'ministry': 'e-Governance Dept, Karnataka', 'beneficiary': 'All Karnataka residents',
     'benefits': 'Online delivery of 800+ government services including certificates and licenses',
     'eligibility': 'Karnataka residents needing government certificates or services',
     'application_url': 'https://sevasindhu.karnataka.gov.in', 'apply_mode': 'online'},
    {'title': 'Karnataka Rajiv Gandhi Housing Scheme', 'category': 'housing', 'level': 'state', 'state': 'Karnataka',
     'ministry': 'Housing Dept, Karnataka', 'beneficiary': 'Houseless SC/ST/OBC families',
     'benefits': 'Free 2BHK housing unit for eligible BPL families',
     'eligibility': 'SC/ST/OBC BPL families without pucca house in Karnataka',
     'application_url': 'https://ashraya.kar.nic.in', 'apply_mode': 'offline'},
    # ── TAMIL NADU ────────────────────────────────────────────────────────────
    {'title': 'Tamil Nadu Kalaignar Magalir Urimai Thogai', 'category': 'women', 'level': 'state', 'state': 'Tamil Nadu',
     'ministry': 'WCD Dept, Tamil Nadu', 'beneficiary': 'Women heads of households',
     'benefits': '₹1,000/month cash transfer to women heads of families',
     'eligibility': 'Women who are heads of families in Tamil Nadu with low income',
     'application_url': 'https://magalivazhurimai.tn.gov.in', 'apply_mode': 'online'},
    {'title': 'Chief Minister Breakfast Scheme TN', 'category': 'education', 'level': 'state', 'state': 'Tamil Nadu',
     'ministry': 'School Education, Tamil Nadu', 'beneficiary': 'Government school students',
     'benefits': 'Free breakfast for all government school students (Class 1–5)',
     'eligibility': 'Students studying in Tamil Nadu government schools',
     'application_url': 'https://cms.tn.gov.in', 'apply_mode': 'offline'},
    {'title': 'Tamil Nadu Chief Minister Health Insurance', 'category': 'healthcare', 'level': 'state', 'state': 'Tamil Nadu',
     'ministry': 'Health Dept, Tamil Nadu', 'beneficiary': 'Government employees and poor',
     'benefits': 'Health insurance coverage for hospitalization expenses',
     'eligibility': 'Government employees and BPL families in Tamil Nadu',
     'application_url': 'https://www.cmchistn.com', 'apply_mode': 'online'},
    # ── KERALA ────────────────────────────────────────────────────────────────
    {'title': 'Kerala Karunya Health Scheme', 'category': 'healthcare', 'level': 'state', 'state': 'Kerala',
     'ministry': 'Health Dept, Kerala', 'beneficiary': 'BPL families and selected categories',
     'benefits': 'Financial assistance for treatment of rare/costly diseases up to ₹2 lakh',
     'eligibility': 'BPL families and government employees in Kerala',
     'application_url': 'https://karunyakerala.org', 'apply_mode': 'online'},
    {'title': 'Kerala Snehapoorvam Scholarship', 'category': 'education', 'level': 'state', 'state': 'Kerala',
     'ministry': 'Social Justice Dept, Kerala', 'beneficiary': 'Orphan and semi-orphan students',
     'benefits': '₹300–₹1,000/month scholarship for students who lost one or both parents',
     'eligibility': 'Students in Kerala who lost one/both parents and have low family income',
     'application_url': 'https://sjd.kerala.gov.in', 'apply_mode': 'online'},
    # ── UTTAR PRADESH ─────────────────────────────────────────────────────────
    {'title': 'UP Kanya Sumangala Yojana', 'category': 'women', 'level': 'state', 'state': 'Uttar Pradesh',
     'ministry': 'WCD Dept, UP', 'beneficiary': 'Girl child from birth to graduation',
     'benefits': '₹15,000 total in 6 installments from birth to graduation',
     'eligibility': 'Girls born after April 1, 2019 in UP with family income < ₹3L/year',
     'application_url': 'https://mksy.up.gov.in', 'apply_mode': 'online'},
    {'title': 'UP Free Laptop Scheme', 'category': 'education', 'level': 'state', 'state': 'Uttar Pradesh',
     'ministry': 'IT Dept, UP', 'beneficiary': 'Class 10/12 pass students',
     'benefits': 'Free laptop for students scoring 65% and above in Class 10/12 Board exams',
     'eligibility': 'UP students who passed Class 10 or 12 with 65%+ marks',
     'application_url': 'https://upcmo.up.nic.in', 'apply_mode': 'online'},
    {'title': 'UP Mukhyamantri Kisan Evam Sarvhit Bima Yojana', 'category': 'farmer', 'level': 'state', 'state': 'Uttar Pradesh',
     'ministry': 'Agriculture Dept, UP', 'beneficiary': 'Farmers and workers aged 18–70',
     'benefits': '₹5 lakh insurance + free treatment up to ₹2.5 lakh on accident',
     'eligibility': 'Farmers and landless workers in UP aged 18–70 below poverty line',
     'application_url': 'https://balrampur.nic.in', 'apply_mode': 'offline'},
    # ── BIHAR ─────────────────────────────────────────────────────────────────
    {'title': 'Bihar Student Credit Card Yojana', 'category': 'education', 'level': 'state', 'state': 'Bihar',
     'ministry': 'Education Dept, Bihar', 'beneficiary': 'Students pursuing higher education',
     'benefits': 'Education loan up to ₹4 lakh at 1% interest for higher studies',
     'eligibility': 'Bihar students who passed Class 12 pursuing higher education aged < 25',
     'application_url': 'https://www.7nishchay-yuvaupmission.bihar.gov.in', 'apply_mode': 'online'},
    {'title': 'Bihar Mukhyamantri Kanya Vivah Yojana', 'category': 'women', 'level': 'state', 'state': 'Bihar',
     'ministry': 'Social Welfare, Bihar', 'beneficiary': 'BPL families with daughters at marriage',
     'benefits': '₹5,000 grant + ₹2,000 check + ₹3,000 dress for marriage',
     'eligibility': 'BPL families in Bihar with daughters of legal marriage age (18+)',
     'application_url': 'https://serviceonline.bihar.gov.in', 'apply_mode': 'online'},
    # ── RAJASTHAN ─────────────────────────────────────────────────────────────
    {'title': 'Chiranjeevi Swasthya Bima Yojana', 'category': 'healthcare', 'level': 'state', 'state': 'Rajasthan',
     'ministry': 'Health Dept, Rajasthan', 'beneficiary': 'All Rajasthan families',
     'benefits': '₹25 lakh/year free medical insurance for every family in Rajasthan',
     'eligibility': 'All families in Rajasthan — register with Jan Aadhar card',
     'application_url': 'https://chiranjeevi.rajasthan.gov.in', 'apply_mode': 'online'},
    {'title': 'Rajasthan Free Mobile Scheme', 'category': 'digital', 'level': 'state', 'state': 'Rajasthan',
     'ministry': 'IT Dept, Rajasthan', 'beneficiary': 'Women heads of household',
     'benefits': 'Free smartphone with 3 years internet to women heads of families',
     'eligibility': 'Women heads of household in Rajasthan with Jan Aadhar enrollment',
     'application_url': 'https://igsy.rajasthan.gov.in', 'apply_mode': 'online'},
    # ── GUJARAT ───────────────────────────────────────────────────────────────
    {'title': 'Mukhyamantri Mahila Utkarsh Yojana', 'category': 'women', 'level': 'state', 'state': 'Gujarat',
     'ministry': 'WCD Dept, Gujarat', 'beneficiary': 'Women SHG members',
     'benefits': 'Interest-free loan up to ₹1 lakh for women SHG members',
     'eligibility': 'Women members of Self Help Groups in Gujarat',
     'application_url': 'https://wmcgujarat.org', 'apply_mode': 'offline'},
    {'title': 'Gujarat Kisan Suryoday Yojana', 'category': 'farmer', 'level': 'state', 'state': 'Gujarat',
     'ministry': 'Energy Dept, Gujarat', 'beneficiary': 'Farmers needing daytime power',
     'benefits': '3-phase electricity supply during 5AM–9PM for agricultural use',
     'eligibility': 'Farmers in Gujarat with registered agricultural connections',
     'application_url': 'https://mgvcl.com', 'apply_mode': 'offline'},
    # ── WEST BENGAL ───────────────────────────────────────────────────────────
    {'title': 'Lakshmir Bhandar', 'category': 'women', 'level': 'state', 'state': 'West Bengal',
     'ministry': 'WCD Dept, West Bengal', 'beneficiary': 'Women heads of household',
     'benefits': '₹500/month (general) or ₹1,000/month (SC/ST) to women heads of family',
     'eligibility': 'Women aged 25–60 who are heads of household in West Bengal',
     'application_url': 'https://wb.gov.in', 'apply_mode': 'offline'},
    {'title': 'Kanyashree Prakalpa', 'category': 'women', 'level': 'state', 'state': 'West Bengal',
     'ministry': 'WCD Dept, West Bengal', 'beneficiary': 'Girls aged 13–18',
     'benefits': '₹750/year (K1) and ₹25,000 one-time grant (K2) for unmarried girls in school',
     'eligibility': 'Unmarried girls aged 13–18 in West Bengal schools, family income < ₹1.2L',
     'application_url': 'https://wbkanyashree.gov.in', 'apply_mode': 'online'},
    # ── HIMACHAL PRADESH ──────────────────────────────────────────────────────
    {'title': 'HP Sahara Yojana', 'category': 'healthcare', 'level': 'state', 'state': 'Himachal Pradesh',
     'ministry': 'Health Dept, HP', 'beneficiary': 'Serious/chronic disease patients',
     'benefits': '₹3,000/month financial assistance for patients with serious illnesses',
     'eligibility': 'HP residents with cancer, parkinson, muscular dystrophy, renal failure, etc.',
     'application_url': 'https://hpsbys.in', 'apply_mode': 'offline'},
    # ── ASSAM ─────────────────────────────────────────────────────────────────
    {'title': 'Orunodoi Scheme', 'category': 'women', 'level': 'state', 'state': 'Assam',
     'ministry': 'Finance Dept, Assam', 'beneficiary': 'Women of BPL/low-income families',
     'benefits': '₹830/month DBT to women members of economically backward families',
     'eligibility': 'Women members of families with income < ₹2L/year in Assam',
     'application_url': 'https://orunodoi.assam.gov.in', 'apply_mode': 'online'},
    # ── ODISHA ────────────────────────────────────────────────────────────────
    {'title': 'KALIA Scheme Odisha', 'category': 'farmer', 'level': 'state', 'state': 'Odisha',
     'ministry': 'Agriculture Dept, Odisha', 'beneficiary': 'Small/marginal farmers',
     'benefits': '₹10,000/year support for cultivation + ₹2,000 for non-cultivation',
     'eligibility': 'Small and marginal farmers in Odisha',
     'application_url': 'https://kalia.odisha.gov.in', 'apply_mode': 'online'},
    {'title': 'Mo Bus — Odisha', 'category': 'transport', 'level': 'state', 'state': 'Odisha',
     'ministry': 'Transport Dept, Odisha', 'beneficiary': 'Students, senior citizens, women',
     'benefits': 'Free bus travel for students, senior citizens and women during specific hours',
     'eligibility': 'Students with school ID, women, senior citizens above 60 in Odisha',
     'application_url': 'https://csmc.co.in', 'apply_mode': 'offline'},
    # ── CENTRAL SCHEMES ───────────────────────────────────────────────────────
    {'title': 'PM Vishwakarma Yojana', 'category': 'msme', 'level': 'central', 'state': '',
     'ministry': 'Ministry of MSME', 'beneficiary': 'Artisans and craftspeople (18 trades)',
     'benefits': '₹1 lakh (Tier 1) + ₹2 lakh (Tier 2) collateral-free loans at 5% interest + tool kit + training',
     'eligibility': 'Artisans/craftspeople in 18 traditional trades (blacksmith, carpenter, potter, etc.)',
     'application_url': 'https://pmvishwakarma.gov.in', 'apply_mode': 'online'},
    {'title': 'PM SVANidhi — Street Vendor Loan', 'category': 'employment', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'Street vendors',
     'benefits': '₹10,000 → ₹20,000 → ₹50,000 working capital loans at subsidized interest',
     'eligibility': 'Street vendors who were vending before March 24, 2020',
     'application_url': 'https://pmsvanidhi.mohua.gov.in', 'apply_mode': 'online'},
    {'title': 'Pradhan Mantri Ujjwala Yojana (PMUY)', 'category': 'women', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Petroleum & Natural Gas', 'beneficiary': 'BPL women without LPG connection',
     'benefits': 'Free LPG connection + stove + first cylinder refill to BPL women',
     'eligibility': 'Women from BPL households without existing LPG connection',
     'application_url': 'https://www.pmuy.gov.in', 'apply_mode': 'online'},
    {'title': 'Jal Jeevan Mission', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Jal Shakti', 'beneficiary': 'Rural households without piped water',
     'benefits': 'Piped drinking water connection to every rural household by 2024',
     'eligibility': 'Rural households without functional household tap connection',
     'application_url': 'https://jaljeevanmission.gov.in', 'apply_mode': 'offline'},
    {'title': 'Saubhagya — Pradhan Mantri Sahaj Bijli Har Ghar Yojana', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Power', 'beneficiary': 'Un-electrified households',
     'benefits': 'Free electricity connection to all un-electrified households',
     'eligibility': 'Un-electrified households in rural areas and urban BPL households',
     'application_url': 'https://saubhagya.gov.in', 'apply_mode': 'offline'},
    {'title': 'PM Suraksha Bima Yojana', 'category': 'pension', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Finance', 'beneficiary': 'Bank account holders aged 18–70',
     'benefits': '₹2 lakh accidental death/full disability insurance at just ₹20/year premium',
     'eligibility': 'Any bank account holder aged 18–70 with auto-debit consent',
     'application_url': 'https://jansuraksha.gov.in', 'apply_mode': 'online'},
    {'title': 'PM Jeevan Jyoti Bima Yojana', 'category': 'pension', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Finance', 'beneficiary': 'Bank account holders aged 18–50',
     'benefits': '₹2 lakh life insurance at ₹436/year premium',
     'eligibility': 'Bank account holders aged 18–50 with auto-debit consent',
     'application_url': 'https://jansuraksha.gov.in', 'apply_mode': 'online'},
    {'title': 'Sukanya Samriddhi Yojana', 'category': 'women', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Finance', 'beneficiary': 'Girl child savings scheme',
     'benefits': '8.2% interest per annum tax-free savings for girl child education/marriage',
     'eligibility': 'Parents of girl children below 10 years of age',
     'application_url': 'https://www.nsiindia.gov.in', 'apply_mode': 'offline'},
    {'title': 'Stand Up India', 'category': 'msme', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Finance / SIDBI', 'beneficiary': 'SC/ST/Women entrepreneurs',
     'benefits': 'Bank loans from ₹10 lakh to ₹1 crore for greenfield enterprises',
     'eligibility': 'SC/ST or Women above 18 years setting up greenfield business (first loan)',
     'application_url': 'https://www.standupmitra.in', 'apply_mode': 'online'},
    {'title': 'PM e-Bus Sewa', 'category': 'transport', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'Urban commuters',
     'benefits': 'Electric bus services in 169 cities to improve public transport',
     'eligibility': 'Citizens in covered cities — use public e-bus services',
     'application_url': 'https://pmebus.gov.in', 'apply_mode': 'offline'},
    {'title': 'National Apprenticeship Promotion Scheme', 'category': 'skill', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Skill Development', 'beneficiary': 'Youth seeking apprenticeship',
     'benefits': '25% of stipend (up to ₹1,500/month) reimbursed to employer; apprentice gets stipend',
     'eligibility': 'Youth aged 14+ who have passed Class 5 minimum; various education levels',
     'application_url': 'https://apprenticeshipindia.org', 'apply_mode': 'online'},
    {'title': 'PM CARE for Children', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Women & Child Development', 'beneficiary': 'Children orphaned due to COVID-19',
     'benefits': '₹10 lakh corpus at 18; free education, health insurance, monthly stipend',
     'eligibility': 'Children who lost both parents or guardian due to COVID-19',
     'application_url': 'https://pmcaresforchildren.in', 'apply_mode': 'online'},
    {'title': 'Swachh Bharat Mission — Toilets', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Jal Shakti', 'beneficiary': 'Households without toilet',
     'benefits': 'Financial assistance of ₹12,000 for construction of individual household toilet',
     'eligibility': 'Rural households without toilet facility',
     'application_url': 'https://sbm.gov.in', 'apply_mode': 'offline'},
    {'title': 'PM Fasal Bima Yojana (PMFBY)', 'category': 'agriculture', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Agriculture', 'beneficiary': 'All farmers growing notified crops',
     'benefits': 'Crop insurance with maximum 2% premium for kharif, 1.5% rabi crops',
     'eligibility': 'All farmers including loanee and non-loanee farmers growing notified crops',
     'application_url': 'https://pmfby.gov.in', 'apply_mode': 'online'},
    {'title': 'Deen Dayal Antyodaya Yojana — NULM', 'category': 'employment', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'Urban poor',
     'benefits': 'Skill training + SHG formation + shelter + street vendor support for urban poor',
     'eligibility': 'Urban poor, street vendors, homeless, SC/ST/minority in urban areas',
     'application_url': 'https://nulm.gov.in', 'apply_mode': 'offline'},
    {'title': 'PM Jan Dhan Yojana', 'category': 'finance', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Finance', 'beneficiary': 'Unbanked citizens',
     'benefits': 'Zero-balance bank account + RuPay debit card + ₹2 lakh accident insurance + overdraft',
     'eligibility': 'Any Indian citizen (10+ years) without a bank account',
     'application_url': 'https://pmjdy.gov.in', 'apply_mode': 'offline'},
    {'title': 'Ayushman Bharat — Health & Wellness Centres', 'category': 'healthcare', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Health', 'beneficiary': 'All citizens',
     'benefits': 'Free primary healthcare at 1.5 lakh+ Health & Wellness Centres',
     'eligibility': 'All Indian citizens; no income criteria for primary care',
     'application_url': 'https://ab-hwc.nhp.gov.in', 'apply_mode': 'offline'},
    {'title': 'National Disability Scholarship', 'category': 'disability', 'level': 'central', 'state': '',
     'ministry': 'Dept of Empowerment of Persons with Disabilities', 'beneficiary': 'Students with disabilities',
     'benefits': '₹5,000–₹20,000/year scholarship for students with 40%+ disability',
     'eligibility': 'Students with minimum 40% disability, income < ₹2.5L/year',
     'application_url': 'https://scholarships.gov.in', 'apply_mode': 'online'},
    {'title': 'PM Awas Yojana PMAY — Credit Linked Subsidy', 'category': 'housing', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'First-time home buyers',
     'benefits': 'Interest subsidy 3-6.5% on home loans up to ₹12 lakh',
     'eligibility': 'First-time home buyer, EWS/LIG/MIG families without pucca house',
     'application_url': 'https://pmaymis.gov.in', 'apply_mode': 'online'},
    {'title': 'National Rural Livelihood Mission (NRLM)', 'category': 'employment', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Rural Development', 'beneficiary': 'Rural BPL women',
     'benefits': 'SHG formation + interest subvention + ₹15,000 revolving fund + bank linkage',
     'eligibility': 'Rural women from BPL households; no upper age limit',
     'application_url': 'https://aajeevika.gov.in', 'apply_mode': 'offline'},
    {'title': 'PM Ujjwala Yojana 2.0', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Petroleum', 'beneficiary': 'Migrant women without LPG',
     'benefits': 'LPG connection with no address proof requirement for migrants',
     'eligibility': 'Migrant women; self-declaration of address acceptable',
     'application_url': 'https://pmuy.gov.in', 'apply_mode': 'online'},
    {'title': 'AMRUT 2.0 — Urban Infrastructure', 'category': 'social', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'Urban residents',
     'benefits': 'Water supply, sewerage, septage, stormwater, urban transport improvements',
     'eligibility': 'Residents of 500 AMRUT cities; applied through local municipal body',
     'application_url': 'https://amrut.gov.in', 'apply_mode': 'offline'},
    {'title': 'National Means-cum-Merit Scholarship (NMMS)', 'category': 'education', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Education', 'beneficiary': 'Class 9–12 meritorious students',
     'benefits': '₹12,000/year scholarship for Class 9–12 students from low-income families',
     'eligibility': 'Students with 55%+ in Class 8, family income < ₹1.5L/year',
     'application_url': 'https://scholarships.gov.in', 'apply_mode': 'online'},
    {'title': 'PM Matru Vandana Yojana', 'category': 'women', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Women & Child Development', 'beneficiary': 'Pregnant and lactating women',
     'benefits': '₹5,000 in 3 instalments for first child; ₹6,000 for second girl child',
     'eligibility': 'All pregnant & lactating women for first child (18+ years)',
     'application_url': 'https://wcd.nic.in/pmmvy', 'apply_mode': 'offline'},
    {'title': 'Pradhan Mantri Laghu Vyapari Maan-Dhan Yojana', 'category': 'pension', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Labour & Employment', 'beneficiary': 'Small traders and shopkeepers',
     'benefits': '₹3,000/month pension for small traders after age 60',
     'eligibility': 'Small traders/shopkeepers/self-employed, aged 18–40, GST turnover < ₹1.5 crore',
     'application_url': 'https://maandhan.in', 'apply_mode': 'online'},
    {'title': 'PM Shram Yogi Maan-Dhan (PM-SYM)', 'category': 'pension', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Labour & Employment', 'beneficiary': 'Unorganized sector workers',
     'benefits': '₹3,000/month pension after age 60 for unorganized workers',
     'eligibility': 'Unorganized workers aged 18–40 with monthly income < ₹15,000',
     'application_url': 'https://maandhan.in', 'apply_mode': 'online'},
    {'title': 'National Urban Livelihoods Mission (NULM) Skills', 'category': 'skill', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Housing & Urban Affairs', 'beneficiary': 'Urban poor youth',
     'benefits': 'Free skill training + placement support for urban poor under NULM',
     'eligibility': 'Urban poor aged 18–45 with family income below poverty line',
     'application_url': 'https://nulm.gov.in', 'apply_mode': 'offline'},
    {'title': 'Samagra Shiksha Abhiyan', 'category': 'education', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Education', 'beneficiary': 'Students from pre-school to Class 12',
     'benefits': 'Free uniforms, textbooks, midday meals, digital education, infrastructure',
     'eligibility': 'All students in government schools from pre-primary to Class 12',
     'application_url': 'https://samagra.education.gov.in', 'apply_mode': 'offline'},
    {'title': 'PM POSHAN (Mid-Day Meal Scheme)', 'category': 'education', 'level': 'central', 'state': '',
     'ministry': 'Ministry of Education', 'beneficiary': 'Government school children',
     'benefits': 'Free hot cooked meal every school day for children in government schools',
     'eligibility': 'All students in Class 1–8 in government/aided schools',
     'application_url': 'https://pmposhan.education.gov.in', 'apply_mode': 'offline'},
]


def seed_expanded_schemes(mongo):
    """Seed all expanded hardcoded schemes"""
    count = 0
    logger.info(f"🔄 Seeding {len(EXPANDED_SCHEMES)} expanded schemes...")
    for scheme in EXPANDED_SCHEMES:
        doc = {
            'title':           scheme['title'],
            'description':     scheme.get('description', scheme.get('benefits', '')),
            'level':           scheme.get('level', 'central'),
            'state':           scheme.get('state', ''),
            'category':        scheme.get('category', 'other'),
            'ministry':        scheme.get('ministry', ''),
            'beneficiary':     scheme.get('beneficiary', ''),
            'benefits':        scheme.get('benefits', ''),
            'eligibility':     scheme.get('eligibility', ''),
            'application_url': scheme.get('application_url', ''),
            'source_url':      scheme.get('application_url', ''),
            'scheme_id':       '',
            'last_updated':    datetime.utcnow().strftime('%Y-%m-%d'),
            'scraped_at':      datetime.utcnow(),
            'is_active':       True,
            'source':          'official_curated',
            'apply_mode':      scheme.get('apply_mode', 'offline'),
        }
        if not doc['description']:
            doc['description'] = doc['benefits']
        upsert_scheme(mongo, doc)
        count += 1
    logger.info(f"✅ Expanded schemes seeded: {count}")
    return count


def run_scraper(mongo):
    """Run all scrapers — targets 5000+ schemes"""
    logger.info("🚀 Starting full scrape cycle...")
    total = 0
    total += seed_expanded_schemes(mongo)      # Curated 70+ high-quality schemes
    total += scrape_myscheme(mongo)            # myscheme.gov.in basic
    total += scrape_myscheme_deep(mongo)       # Deep paginated scrape
    total += scrape_india_gov_api(mongo)       # data.gov.in APIs
    total += scrape_ministry_websites(mongo)   # Ministry websites
    total += scrape_state_schemes(mongo)       # State scheme list
    total_in_db = mongo.db.schemes.count_documents({'is_active': True})
    logger.info(f"🏁 Scrape complete. Processed: {total} | Total in DB: {total_in_db}")
    return total


def seed_sample_data(mongo):
    """Seed initial data"""
    if mongo.db.schemes.count_documents({}) > 0:
        logger.info("DB already has data, running update scrape...")
        run_scraper(mongo)
        return
    logger.info("Seeding initial data...")
    run_scraper(mongo)


def start_scheduler(mongo):
    """Start hourly background scraper"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: run_scraper(mongo), 'interval', hours=1, id='scheme_scraper')
    scheduler.start()
    logger.info("⏰ Hourly scraper scheduled")
    return scheduler