import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import json
import re
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import PyPDF2
import pandas as pd
from datetime import datetime
import requests
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Production configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Get API key from environment variable
api_key = os.environ.get("TYPHOON_OCR_API_KEY")
if not api_key:
    logger.warning("TYPHOON_OCR_API_KEY not found in environment variables")
    # Don't fail completely, just log warning
else:
    logger.info("TYPHOON_OCR_API_KEY found")

# Configuration for different environments
IS_PRODUCTION = os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('FLASK_ENV') == 'production'

if IS_PRODUCTION:
    UPLOAD_FOLDER = '/tmp/uploads'
    RESULTS_FOLDER = '/tmp/results'
    DEBUG_FOLDER = '/tmp/debug'
    logger.info("Running in production mode")
else:
    UPLOAD_FOLDER = 'uploads'
    RESULTS_FOLDER = 'results'
    DEBUG_FOLDER = 'debug'
    logger.info("Running in development mode")

ALLOWED_EXTENSIONS = {'pdf'}

# Create directories if they don't exist
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(RESULTS_FOLDER, exist_ok=True)
    os.makedirs(DEBUG_FOLDER, exist_ok=True)
    logger.info(f"Directories created: {UPLOAD_FOLDER}, {RESULTS_FOLDER}, {DEBUG_FOLDER}")
except Exception as e:
    logger.error(f"Failed to create directories: {e}")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pdf_page_count(pdf_path):
    """Get the total number of pages in a PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            return len(pdf_reader.pages)
    except Exception as e:
        logger.error(f"Error reading PDF: {e}")
        return 1

# Simple mock OCR function for testing
def mock_ocr_document(pdf_path, page_num=1):
    """Mock OCR function for testing when typhoon-ocr is not available"""
    logger.info(f"Mock OCR processing page {page_num} of {pdf_path}")
    
    # Return mock data that matches expected format
    return """
TikTok Shop

J&T EXPRESS

ถึง ทดสอบ ผู้รับ
123/45 ม.6 ต.ทดสอบ อ.ทดสอบ จ.ทดสอบ, ทดสอบ, ทดสอบ, 12345

Order ID
123456789

Shipping Date:
11/06/2025 23:59
"""

def extract_shipping_info(text):
    """Extract shipping information from OCR text"""
    extracted_data = {
        "recipient_name": "",
        "recipient_address": "",
        "parsed_address": {},
        "order_id": "",
        "shipping_date": ""
    }
    
    try:
        # Extract recipient info
        recipient_pattern = r'ถึง\s+(.+?)\n((?:.+?\n)*?)(?=\(\+\)|COD|Weight|\n\n|Order|$)'
        recipient_match = re.search(recipient_pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        
        if recipient_match:
            extracted_data["recipient_name"] = recipient_match.group(1).strip()
            raw_address = recipient_match.group(2).strip()
            raw_address = re.sub(r'\n+', ' ', raw_address)
            raw_address = re.sub(r'\s+', ' ', raw_address)
            extracted_data["recipient_address"] = raw_address
            
            # Simple address parsing
            parts = [part.strip() for part in raw_address.split(',') if part.strip()]
            extracted_data["parsed_address"] = {
                "full_address": raw_address,
                "street_address": parts[0] if len(parts) > 0 else "",
                "district": parts[1] if len(parts) > 1 else "",
                "province": parts[2] if len(parts) > 2 else "",
                "postal_code": ""
            }
            
            # Extract postal code
            postal_match = re.search(r'\d{5}', raw_address)
            if postal_match:
                extracted_data["parsed_address"]["postal_code"] = postal_match.group()
        
        # Extract Order ID
        order_id_match = re.search(r'Order ID\s*:?\s*\n?(\d+)', text, re.IGNORECASE)
        if order_id_match:
            extracted_data["order_id"] = order_id_match.group(1).strip()
        
        # Extract Shipping Date
        shipping_date_match = re.search(r'Shipping Date:\s*\n?(.+?)(?:\n|\r|$)', text, re.IGNORECASE)
        if shipping_date_match:
            extracted_data["shipping_date"] = shipping_date_match.group(1).strip()
        
    except Exception as e:
        logger.error(f"Error extracting shipping info: {e}")
    
    return extracted_data

def ocr_pdf_pages(pdf_path, max_pages=None, task_type="default", debug_mode=False):
    """OCR PDF pages and extract shipping information"""
    
    total_pages = get_pdf_page_count(pdf_path)
    pages_to_process = total_pages if max_pages is None else min(max_pages, total_pages)
    
    results = {
        "document": os.path.basename(pdf_path),
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "extracted_orders": [],
        "processing_status": "success",
        "debug_pages": [] if debug_mode else None
    }
    
    # Process each page
    for page_num in range(1, pages_to_process + 1):
        logger.info(f"Processing page {page_num}/{pages_to_process}")
        
        try:
            # Use mock OCR for now
            markdown = mock_ocr_document(pdf_path, page_num)
            shipping_info = extract_shipping_info(markdown)
            
            # Only add if we found relevant data
            if shipping_info["order_id"] or shipping_info["recipient_name"]:
                order_data = {
                    "page": page_num,
                    "recipient_name": shipping_info["recipient_name"],
                    "recipient_address": shipping_info["recipient_address"],
                    "parsed_address": shipping_info["parsed_address"],
                    "order_id": shipping_info["order_id"],
                    "shipping_date": shipping_info["shipping_date"]
                }
                results["extracted_orders"].append(order_data)
            
        except Exception as e:
            logger.error(f"Error processing page {page_num}: {e}")
            results["processing_status"] = "partial_success"
    
    return results

def create_excel_file(results, filename):
    """Create Excel file from results"""
    excel_data = []
    
    for order in results["extracted_orders"]:
        row = {
            'หน้า': order['page'],
            'Order ID': order['order_id'],
            'ชื่อผู้รับ': order['recipient_name'],
            'วันที่จัดส่ง': order['shipping_date'],
            'ที่อยู่เดิม': order['recipient_address'],
            'ที่อยู่ละเอียด': order['parsed_address'].get('street_address', ''),
            'อำเภอ': order['parsed_address'].get('district', ''),
            'จังหวัด': order['parsed_address'].get('province', ''),
            'รหัสไปรษณีย์': order['parsed_address'].get('postal_code', '')
        }
        excel_data.append(row)
    
    df = pd.DataFrame(excel_data)
    excel_path = os.path.join(RESULTS_FOLDER, filename)
    
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='ข้อมูลการจัดส่ง', index=False)
    
    return excel_path

# Routes
@app.route('/')
def index():
    logger.info("Index page accessed")
    return render_template('index.html')

# Add this near the top after app creation
@app.before_first_request
def startup_info():
    port = os.environ.get('PORT', 'NOT_SET')
    logger.info(f"=== APPLICATION STARTUP ===")
    logger.info(f"PORT environment variable: {port}")
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Flask app: {app}")
    logger.info(f"App config: {dict(app.config)}")

# Enhance health check
@app.route('/health')
def health_check():
    """Enhanced health check endpoint"""
    try:
        port = os.environ.get('PORT', 'NOT_SET')
        logger.info(f"Health check requested - PORT: {port}")
        
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "environment": "production" if IS_PRODUCTION else "development",
            "port": port,
            "pid": os.getpid(),
            "directories": {
                "upload": UPLOAD_FOLDER,
                "results": RESULTS_FOLDER,
                "debug": DEBUG_FOLDER
            }
        }
        
        # Test directory access
        for name, path in health_data["directories"].items():
            health_data[f"{name}_exists"] = os.path.exists(path)
            health_data[f"{name}_writable"] = os.access(path, os.W_OK)
        
        return jsonify(health_data)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    logger.info("Upload request received")
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        max_pages = request.form.get('max_pages', type=int)
        debug_mode = request.form.get('debug_mode', 'false').lower() == 'true'
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            logger.info(f"File saved: {filepath}")
            
            # Process the PDF
            results = ocr_pdf_pages(filepath, max_pages, debug_mode=debug_mode)
            
            # Create timestamps and filenames
            base_filename = filename.replace('.pdf', '')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save JSON results
            json_filename = f"result_{base_filename}_{timestamp}.json"
            json_path = os.path.join(RESULTS_FOLDER, json_filename)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            # Create Excel file
            excel_filename = f"result_{base_filename}_{timestamp}.xlsx"
            excel_path = create_excel_file(results, excel_filename)
            
            download_urls = {
                'json': f'/download/{json_filename}',
                'excel': f'/download/{excel_filename}'
            }
            
            logger.info(f"Processing completed: {len(results['extracted_orders'])} orders found")
            
            return jsonify({
                'success': True,
                'results': results,
                'download_urls': download_urls,
                'debug_mode': debug_mode
            })
            
        return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400
        
    except Exception as e:
        logger.error(f"Upload processing error: {e}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500
    
    finally:
        # Clean up uploaded file
        if 'filepath' in locals() and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Cleaned up file: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to clean up file: {e}")

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_file(os.path.join(RESULTS_FOLDER, filename), as_attachment=True)
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': 'File not found'}), 404

# Error handlers
@app.errorhandler(413)
def file_too_large(error):
    return jsonify({'error': 'File too large', 'message': 'Maximum file size is 50MB'}), 413

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"=== DIRECT RUN ===")
    logger.info(f"Starting application on port {port}")
    logger.info(f"Debug mode: {not IS_PRODUCTION}")
    app.run(host='0.0.0.0', port=port, debug=not IS_PRODUCTION)