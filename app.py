import requests
import json
import hashlib
import hmac
import base64
import os
from datetime import datetime
from urllib.parse import quote
import pandas as pd
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import logging
import re

# ====== Cấu hình logging ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load biến môi trường
load_dotenv()
app = Flask(__name__)

# Cấu hình CORS
allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
CORS(
    app,
    resources={r"/*": {
        "origins": allowed_origins,
        "supports_credentials": True,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "expose_headers": ["Content-Type"]
    }}
)

# Environment variables
X_ApiKey = os.getenv("GENIUSLINK_API_KEY")
X_ApiSecret = os.getenv("GENIUSLINK_API_SECRET")
access_key = os.getenv("AMAZON_ACCESS_KEY")
secret_key = os.getenv("AMAZON_SECRET_KEY")

access_key = re.sub(r"'", "", access_key)

# ==== GENIUSLINK SHORT URL ====
def geniuslink(link):
    """Generate shortened link using Geniuslink API"""
    if not X_ApiKey or not X_ApiSecret:
        print("Geniuslink credentials not found, returning original link")
        return link
        
    url = "https://api.geni.us/v3/shorturls"
    headers = {
        "X-Api-Key": X_ApiKey,
        "X-Api-Secret": X_ApiSecret,
        "Content-Type": "application/json"
    }
    payload = {
        "url": link,
        "groupId": 385268,
        "fetchMetadata": True
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            return data['shortUrl']['productUrl']
        else:
            print(f"Geniuslink Error: {response.status_code}, {response.text}")
            return link
    except Exception as e:
        print(f"Geniuslink Exception: {str(e)}")
        return link

# ==== AMAZON PRODUCT API ====
class AmazonProductAPI:
    def __init__(self):
        self.endpoint = 'https://webservices.amazon.com/paapi5/searchitems'
        self.host = 'webservices.amazon.com'
        self.region = 'us-east-1'
        self.service = 'ProductAdvertisingAPI'
        self.access_key = access_key
        self.secret_key = secret_key
        self.partner_tag = "homefind0d5-20"

    def _create_auth_headers(self, payload):
        """Create authentication headers for the API request"""
        t = datetime.utcnow()
        amz_date = t.strftime('%Y%m%dT%H%M%SZ')
        date_stamp = t.strftime('%Y%m%d')

        service = 'ProductAdvertisingAPI'
        target = 'com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems'
        content_encoding = 'amz-1.0'
        content_type = 'application/json; charset=utf-8'
        path = '/paapi5/searchitems'

        payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()

        header_map = {
            'content-encoding': content_encoding,
            'content-type': content_type,
            'host': self.host,
            'x-amz-date': amz_date,
            'x-amz-target': target
        }

        sorted_headers = sorted(header_map.keys())
        canonical_headers_lines = []
        signed_headers_list = []

        for key in sorted_headers:
            canonical_headers_lines.append(f'{key}:{header_map[key]}')
            signed_headers_list.append(key)

        canonical_headers = '\n'.join(canonical_headers_lines) + '\n'
        signed_headers = ';'.join(signed_headers_list)

        method = 'POST'
        query_string = ''

        canonical_request = (
            f'{method}\n'
            f'{path}\n'
            f'{query_string}\n'
            f'{canonical_headers}\n'
            f'{signed_headers}\n'
            f'{payload_hash}'
        )

        algorithm = 'AWS4-HMAC-SHA256'
        credential_scope = f'{date_stamp}/{self.region}/{self.service}/aws4_request'
        canonical_request_hash = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()

        string_to_sign = (
            f'{algorithm}\n'
            f'{amz_date}\n'
            f'{credential_scope}\n'
            f'{canonical_request_hash}'
        )

        signing_key = self._get_signature_key(self.secret_key, date_stamp, self.region, self.service)
        signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        authorization_header = f"{algorithm} Credential={self.access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        
        return {
            'Authorization': authorization_header,
            'Content-Encoding': content_encoding,
            'Content-Type': content_type,
            'Host': self.host,
            'X-Amz-Date': amz_date,
            'X-Amz-Target': target
        }

    def _get_signature_key(self, key, date_stamp, region_name, service_name):
        """Generate the signing key using the AWS Signature Version 4 signing process"""
        k_secret = ('AWS4' + key).encode('utf-8')
        k_date = self._sign(k_secret, date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, 'aws4_request')
        return k_signing

    def _sign(self, key, msg):
        """Create an HMAC-SHA256 hash"""
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    def search_products(self, keywords, item_count=10, search_index='All', item_page=1):
        if not self.access_key or not self.secret_key:
            return {'error': 'Amazon API credentials not configured'}
        
        # Updated payload with ByLineInfo để lấy brand
        payload = {
            "Keywords": keywords,
            "Resources": [
                "Images.Primary.Medium",
                "Images.Primary.Large",
                "ItemInfo.Title",
                "ItemInfo.ProductInfo",
                "ItemInfo.Features",
                "ItemInfo.TechnicalInfo",
                "ItemInfo.ManufactureInfo",
                "ItemInfo.ByLineInfo",  
                "Offers.Listings.Price",
                "Offers.Listings.DeliveryInfo.IsAmazonFulfilled",
                "Offers.Listings.DeliveryInfo.IsFreeShippingEligible",
                "Offers.Listings.Availability.MaxOrderQuantity",
                "Offers.Listings.Availability.Message",
                "Offers.Listings.Availability.MinOrderQuantity",
                "Offers.Listings.Availability.Type",
                "Offers.Summaries.HighestPrice",
                "Offers.Summaries.LowestPrice",
                "CustomerReviews.Count",      
                "CustomerReviews.StarRating"   
            ],
            "PartnerTag": self.partner_tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.com",
            "SearchIndex": search_index,
            "ItemCount": min(item_count, 10),
            "ItemPage": item_page
        }
        
        payload_json = json.dumps(payload)
        headers = self._create_auth_headers(payload_json)
        
        try:
            response = requests.post(self.endpoint, data=payload_json, headers=headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f'API request failed: {response.status_code}', 'response_text': response.text}
        except requests.exceptions.RequestException as e:
            return {'error': f'Request failed: {str(e)}'}


    def extract_product_links(self, api_response):
        """Extract product fields with real star rating and review count from CustomerReviews."""
        products = []

        items = api_response.get('SearchResult', {}).get('Items', []) if api_response else []
        for item in items:
            product = {
                'asin': item.get('ASIN', ''),
                'title': item.get('ItemInfo', {}).get('Title', {}).get('DisplayValue', ''),
                'price': '',
                'originalPrice': '',
                'imageUrl': '',
                'detailPageUrl': '',
                'brand': '',
                'availability': '',
                'rating': '',        # số sao trung bình (float/string)
                'reviewCount': ''    # số lượt review (int/string)
            }

            # detail URL
            if product['asin']:
                product['detailPageUrl'] = item.get(
                    'DetailPageURL',
                    f"https://www.amazon.com/dp/{product['asin']}?tag={self.partner_tag}"
                )

            # Brand
            brand_display = item.get('ItemInfo', {}).get('ByLineInfo', {}).get('Brand', {}).get('DisplayValue')
            if brand_display:
                product['brand'] = brand_display

            # Pricing
            if 'Offers' in item:
                if 'Listings' in item['Offers'] and item['Offers']['Listings']:
                    first_listing = item['Offers']['Listings'][0]
                    if 'Price' in first_listing and 'DisplayAmount' in first_listing['Price']:
                        product['price'] = first_listing['Price']['DisplayAmount']
                    if 'Availability' in first_listing and 'Message' in first_listing['Availability']:
                        product['availability'] = first_listing['Availability']['Message']

                if 'Summaries' in item['Offers'] and item['Offers']['Summaries']:
                    summaries = item['Offers']['Summaries'][0]
                    if 'HighestPrice' in summaries and 'DisplayAmount' in summaries['HighestPrice']:
                        highest_price = summaries['HighestPrice']['DisplayAmount']
                        if highest_price != product['price']:
                            product['originalPrice'] = highest_price

            # Image
            if 'Images' in item and 'Primary' in item['Images']:
                primary_image = item['Images']['Primary']
                if 'Large' in primary_image and 'URL' in primary_image['Large']:
                    product['imageUrl'] = primary_image['Large']['URL']
                elif 'Medium' in primary_image and 'URL' in primary_image['Medium']:
                    product['imageUrl'] = primary_image['Medium']['URL']

            # Fallback defaults
            if not product['availability']:
                product['availability'] = 'In Stock'
            if not product['price']:
                product['price'] = 'Price not available'

            products.append(product)

        return products

api = AmazonProductAPI()

def search_products_paginated(keywords, page=1, items_per_page=10):
    """Search products with enhanced data extraction"""
    response = api.search_products(keywords, item_count=items_per_page, item_page=page)
    
    if 'error' in response:
        return {'error': response['error']}
    
    products = api.extract_product_links(response)
    results = []
    
    for product in products:
        if not product.get('title', '').strip():
            continue
        
        # Generate shortened link
        short_link = geniuslink(product['detailPageUrl'])
        
        # Prepare the product data with all required fields
        product_data = {
            'asin': product['asin'],
            'title': product['title'],
            'price': product['price'],
            'originalPrice': product['originalPrice'],
            'imageUrl': product['imageUrl'],
            'detailPageUrl': short_link,  # Use shortened link
            'link': short_link,  # For backward compatibility
            'brand': product['brand'],
            'availability': product['availability'],
            'rating': product['rating'],
            'reviewCount': product['reviewCount'],
            'original_link': product['detailPageUrl']  # Keep original for reference
        }
        
        results.append(product_data)
    
    return results

# ==== ROUTES ====
@app.route('/')
def index():
    """Trang chủ - hiển thị form tìm kiếm hoặc kết quả tìm kiếm"""
    keywords = request.args.get('q', '').strip()
    
    if not keywords:
        return render_template('results.html', keywords='', products=[], current_page=1, show_search_form=True)
    
    logger.info(f"Direct search from homepage with keywords: '{keywords}'")
    
    results = search_products_paginated(keywords, page=1, items_per_page=10)
    
    if isinstance(results, dict) and "error" in results:
        logger.error(f"Search error: {results['error']}", exc_info=True)
        return render_template('results.html', keywords=keywords, products=[], current_page=1, 
                             error=f"Search error: {results['error']}", show_search_form=True)
    
    logger.info(f"Found {len(results)} products for keyword '{keywords}'")
    
    return render_template('results.html', keywords=keywords, products=results, current_page=1, show_search_form=True)

@app.route('/search', methods=['POST', 'GET'])
def search():
    """Route xử lý tìm kiếm - redirect về trang chủ với query parameter"""
    if request.method == 'POST':
        keywords = request.form.get('keywords', '').strip()
    else:
        keywords = request.args.get('q', '').strip()
    
    logger.info(f"Search request - Keywords: '{keywords}'")
    
    if keywords:
        return render_template('results.html', keywords=keywords, products=[], current_page=1, redirect_search=True)
    else:
        return render_template('results.html', keywords='', products=[], current_page=1, 
                             error="Please enter a search keyword", show_search_form=True)

@app.route('/load_more', methods=['POST'])
def load_more():
    """Load more products for pagination"""
    data = request.get_json()
    keywords = data.get('keywords', '').strip()
    current_page = data.get('page', 1)
    
    if not keywords:
        return jsonify({"error": "Missing keywords"}), 400
    
    next_page = current_page + 1
    results = search_products_paginated(keywords, page=next_page, items_per_page=10)
    
    if isinstance(results, dict) and "error" in results:
        return jsonify(results), 500
    
    return jsonify({"products": results, "page": next_page, "has_more": len(results) >= 10})

@app.route('/api/search', methods=['GET'])
def api_search():
    """API endpoint for search"""
    query = request.args.get('q')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    
    if not query:
        return jsonify({"error": "Missing query parameter q"}), 400
    
    results = search_products_paginated(query, page=page, items_per_page=per_page)
    
    if isinstance(results, dict) and "error" in results:
        return jsonify(results), 500
    
    return jsonify({
        "query": query, 
        "products": results, 
        "page": page, 
        "per_page": per_page, 
        "total": len(results)
    })

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host="0.0.0.0", port=port)