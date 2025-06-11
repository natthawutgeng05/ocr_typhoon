import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

import json
import re
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from typhoon_ocr import ocr_document
import PyPDF2
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# Production configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Get API key from environment variable - SECURE
api_key = os.environ.get("TYPHOON_OCR_API_KEY")
if not api_key:
    raise ValueError("TYPHOON_OCR_API_KEY environment variable is required")

os.environ["TYPHOON_OCR_API_KEY"] = api_key

# Configuration - Detect platform and set folders
IS_RENDER = os.environ.get('RENDER') is not None
IS_RAILWAY = os.environ.get('RAILWAY_ENVIRONMENT') is not None
IS_PRODUCTION = IS_RENDER or IS_RAILWAY or os.environ.get('FLASK_ENV') == 'production'

if IS_PRODUCTION:
    UPLOAD_FOLDER = '/tmp/uploads'
    RESULTS_FOLDER = '/tmp/results'
    DEBUG_FOLDER = '/tmp/debug'
else:
    UPLOAD_FOLDER = 'uploads'
    RESULTS_FOLDER = 'results'
    DEBUG_FOLDER = 'debug'

ALLOWED_EXTENSIONS = {'pdf'}

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)
os.makedirs(DEBUG_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pdf_page_count(pdf_path):
    """Get the total number of pages in a PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            return len(pdf_reader.pages)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return 1

def parse_address(address_text):
    """Parse address text separated by commas with debug info - IMPROVED"""
    debug_info = {
        "original": address_text,
        "split_parts": [],
        "parsing_notes": []
    }
    
    # Clean up the address text first
    cleaned_address = re.sub(r'\s+', ' ', address_text.strip())
    debug_info["cleaned_address"] = cleaned_address
    
    # Split by comma and clean up
    parts = [part.strip() for part in cleaned_address.split(',') if part.strip()]
    debug_info["split_parts"] = parts
    debug_info["parsing_notes"].append(f"Split into {len(parts)} parts")
    
    address_data = {
        "full_address": address_text,
        "street_address": "",
        "district": "",
        "province": "",
        "postal_code": "",
        "debug": debug_info
    }
    
    if len(parts) >= 1:
        address_data["street_address"] = parts[0]
        debug_info["parsing_notes"].append(f"Street address: '{parts[0]}'")
    if len(parts) >= 2:
        address_data["district"] = parts[1]
        debug_info["parsing_notes"].append(f"District: '{parts[1]}'")
    if len(parts) >= 3:
        address_data["province"] = parts[2]
        debug_info["parsing_notes"].append(f"Province: '{parts[2]}'")
    if len(parts) >= 4:
        # Extract postal code (usually numbers)
        postal_match = re.search(r'\d{5}', parts[3])
        if postal_match:
            address_data["postal_code"] = postal_match.group()
            debug_info["parsing_notes"].append(f"Found postal code: {postal_match.group()}")
        else:
            debug_info["parsing_notes"].append(f"No postal code found in: '{parts[3]}'")
    
    # If we have more than 4 parts, try to find postal code in any part
    if not address_data["postal_code"] and len(parts) > 4:
        for i, part in enumerate(parts):
            postal_match = re.search(r'\d{5}', part)
            if postal_match:
                address_data["postal_code"] = postal_match.group()
                debug_info["parsing_notes"].append(f"Found postal code in part {i}: {postal_match.group()}")
                break
    
    return address_data

def extract_shipping_info(text):
    """Extract specific shipping information from OCR text - SIMPLE VERSION"""
    extracted_data = {
        "recipient_name": "",
        "recipient_address": "",
        "parsed_address": {},
        "order_id": "",
        "shipping_date": ""
    }
    
    # Extract recipient info with improved multi-line pattern
    recipient_pattern = r'ถึง\s+(.+?)\n((?:.+?\n)*?)(?=\(\+\)|COD|Weight|\n\n|$)'
    recipient_match = re.search(recipient_pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    
    if recipient_match:
        extracted_data["recipient_name"] = recipient_match.group(1).strip()
        raw_address = recipient_match.group(2).strip()
        # Clean up newlines and extra spaces
        raw_address = re.sub(r'\n+', ' ', raw_address)
        raw_address = re.sub(r'\s+', ' ', raw_address)
        extracted_data["recipient_address"] = raw_address
        extracted_data["parsed_address"] = parse_address(raw_address)
    else:
        # Fallback: try to extract just the name
        name_match = re.search(r'ถึง\s+(.+?)(?:\n|\r)', text, re.IGNORECASE)
        if name_match:
            extracted_data["recipient_name"] = name_match.group(1).strip()
    
    # Extract Order ID
    order_id_match = re.search(r'Order ID\s*:?\s*\n?(\d+)', text, re.IGNORECASE)
    if order_id_match:
        extracted_data["order_id"] = order_id_match.group(1).strip()
    
    # Extract Shipping Date
    shipping_date_match = re.search(r'Shipping Date:\s*\n?(.+?)(?:\n|\r)', text, re.IGNORECASE)
    if shipping_date_match:
        extracted_data["shipping_date"] = shipping_date_match.group(1).strip()
    
    return extracted_data

def extract_shipping_info_debug(text):
    """Extract specific shipping information from OCR text with detailed debug"""
    debug_info = {
        "raw_text_length": len(text),
        "raw_text_preview": text[:500] + "..." if len(text) > 500 else text,
        "recipient_patterns_tried": [],
        "order_id_patterns_tried": [],
        "shipping_date_patterns_tried": [],
        "matches_found": {}
    }
    
    extracted_data = {
        "recipient_name": "",
        "recipient_address": "",
        "parsed_address": {},
        "order_id": "",
        "shipping_date": "",
        "debug": debug_info
    }
    
    # Try multiple patterns for recipient info - IMPROVED PATTERNS
    recipient_patterns = [
        # Pattern 1: ถึง + name + multi-line address until phone number
        r'ถึง\s+(.+?)\n((?:.+\n)*?)(?:\(\+\)|COD|Weight)',
        # Pattern 2: ถึง + name + address lines until next section
        r'ถึง\s+(.+?)\n((?:[^\n]+\n?)*?)(?=\n\(\+\)|\nCOD|\nWeight)',
        # Pattern 3: ถึง + name + exactly 2 lines
        r'ถึง\s+(.+?)\n(.+?)\n(.+?)(?:\n|$)',
        # Pattern 4: Original pattern as fallback
        r'ถึง\s+(.+?)(?:\n|\r)(.+?)(?:\n|\r)',
    ]
    
    for i, pattern in enumerate(recipient_patterns):
        debug_info["recipient_patterns_tried"].append({
            "pattern": pattern,
            "flags": "re.IGNORECASE | re.DOTALL | re.MULTILINE"
        })
        
        recipient_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if recipient_match:
            extracted_data["recipient_name"] = recipient_match.group(1).strip()
            
            # Handle different group structures
            if len(recipient_match.groups()) >= 3:
                # Pattern 3: has 3 groups (name + line1 + line2)
                address_parts = [recipient_match.group(2).strip(), recipient_match.group(3).strip()]
                raw_address = ', '.join(part for part in address_parts if part)
            else:
                # Pattern 1, 2, 4: has 2 groups (name + address)
                raw_address = recipient_match.group(2).strip()
                # Clean up extra newlines and spaces
                raw_address = re.sub(r'\n+', ' ', raw_address)
                raw_address = re.sub(r'\s+', ' ', raw_address)
            
            extracted_data["recipient_address"] = raw_address
            extracted_data["parsed_address"] = parse_address(raw_address)
            
            debug_info["matches_found"]["recipient"] = {
                "pattern_index": i,
                "pattern_used": pattern,
                "name": extracted_data["recipient_name"],
                "address": raw_address,
                "groups": recipient_match.groups(),
                "raw_match": recipient_match.group(0)
            }
            break
    
    # If no multi-line pattern worked, try to manually extract address lines
    if not extracted_data["recipient_address"] and extracted_data["recipient_name"]:
        debug_info["matches_found"]["manual_address_extraction"] = "Attempting manual extraction"
        
        # Find the line with recipient name
        lines = text.split('\n')
        recipient_line_index = None
        
        for i, line in enumerate(lines):
            if 'ถึง' in line and extracted_data["recipient_name"] in line:
                recipient_line_index = i
                break
        
        if recipient_line_index is not None:
            # Collect address lines after recipient name until we hit phone number or other section
            address_lines = []
            for i in range(recipient_line_index + 1, min(recipient_line_index + 5, len(lines))):
                if i < len(lines):
                    line = lines[i].strip()
                    # Stop if we hit phone number, COD, or empty line
                    if line.startswith('(+)') or line == 'COD' or line.startswith('Weight') or not line:
                        break
                    address_lines.append(line)
            
            if address_lines:
                raw_address = ' '.join(address_lines)
                extracted_data["recipient_address"] = raw_address
                extracted_data["parsed_address"] = parse_address(raw_address)
                
                debug_info["matches_found"]["manual_extraction"] = {
                    "address_lines": address_lines,
                    "combined_address": raw_address
                }
    
    # Extract Order ID patterns (unchanged)
    order_patterns = [
        r'Order ID\s*:?\s*\n?(\d+)',
        r'Order ID\s*:?\s*(\d+)',
        r'Order\s+ID\s*:?\s*(\d+)',
        r'OrderID\s*:?\s*(\d+)',
        r'order\s+id\s*:?\s*(\d+)',
    ]
    
    for i, pattern in enumerate(order_patterns):
        debug_info["order_id_patterns_tried"].append(pattern)
        order_id_match = re.search(pattern, text, re.IGNORECASE)
        if order_id_match:
            extracted_data["order_id"] = order_id_match.group(1).strip()
            debug_info["matches_found"]["order_id"] = {
                "pattern_index": i,
                "value": extracted_data["order_id"],
                "full_match": order_id_match.group(0)
            }
            break
    
    # Extract Shipping Date patterns (unchanged)
    shipping_patterns = [
        r'Shipping Date:\s*\n?(.+?)(?:\n|\r)',
        r'Shipping Date:\s*(.+?)(?:\n|\r)',
        r'shipping\s+date:\s*(.+?)(?:\n|\r)',
        r'Ship Date:\s*(.+?)(?:\n|\r)',
        r'Date:\s*(.+?)(?:\n|\r)',
    ]
    
    for i, pattern in enumerate(shipping_patterns):
        debug_info["shipping_date_patterns_tried"].append(pattern)
        shipping_date_match = re.search(pattern, text, re.IGNORECASE)
        if shipping_date_match:
            extracted_data["shipping_date"] = shipping_date_match.group(1).strip()
            debug_info["matches_found"]["shipping_date"] = {
                "pattern_index": i,
                "value": extracted_data["shipping_date"],
                "full_match": shipping_date_match.group(0)
            }
            break
    
    return extracted_data

def create_debug_file(results, filename):
    """Create detailed debug file"""
    debug_data = {
        "extraction_summary": {
            "total_pages_processed": results["processed_pages"],
            "orders_found": len(results["extracted_orders"]),
            "pages_with_data": [order["page"] for order in results["extracted_orders"]],
            "pages_without_data": []
        },
        "page_details": []
    }
    
    # Find pages without data
    found_pages = set(order["page"] for order in results["extracted_orders"])
    all_pages = set(range(1, results["processed_pages"] + 1))
    debug_data["extraction_summary"]["pages_without_data"] = list(all_pages - found_pages)
    
    # Add debug info for each page
    if "debug_pages" in results:
        debug_data["page_details"] = results["debug_pages"]
    
    debug_path = os.path.join(DEBUG_FOLDER, filename)
    with open(debug_path, 'w', encoding='utf-8') as f:
        json.dump(debug_data, f, ensure_ascii=False, indent=2)
    
    return debug_path

def create_excel_file(results, filename):
    """Create Excel file from results"""
    # Prepare data for Excel
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
    
    # Create DataFrame
    df = pd.DataFrame(excel_data)
    
    # Create Excel file with multiple sheets
    excel_path = os.path.join(RESULTS_FOLDER, filename)
    
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        # Main data sheet
        df.to_excel(writer, sheet_name='ข้อมูลการจัดส่ง', index=False)
        
        # Summary sheet
        summary_data = {
            'รายละเอียด': [
                'ชื่อไฟล์',
                'จำนวนหน้าทั้งหมด',
                'จำนวนหน้าที่ประมวลผล',
                'จำนวนคำสั่งซื้อที่พบ',
                'วันที่ประมวลผล'
            ],
            'ค่า': [
                results['document'],
                results['total_pages'],
                results['processed_pages'],
                len(results['extracted_orders']),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='สรุปผลลัพธ์', index=False)
        
        # Auto-adjust column widths
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
    
    return excel_path

def ocr_pdf_pages(pdf_path, max_pages=None, task_type="default", debug_mode=False):
    """OCR PDF pages and extract shipping information with debug"""
    
    # Get total pages
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
        print(f"Processing page {page_num}/{pages_to_process}...")
        
        try:
            markdown = ocr_document(
                pdf_or_image_path=pdf_path,
                task_type=task_type,
                page_num=page_num
            )
            
            # Extract shipping info - FIXED: Choose function based on debug mode
            if debug_mode:
                shipping_info = extract_shipping_info_debug(markdown)
                
                # Store debug info
                debug_page_info = {
                    "page_number": page_num,
                    "raw_ocr_text": markdown,
                    "raw_text_length": len(markdown),
                    "extraction_debug": shipping_info.get("debug", {}),
                    "extracted_data": {
                        "recipient_name": shipping_info["recipient_name"],
                        "recipient_address": shipping_info["recipient_address"],
                        "order_id": shipping_info["order_id"],
                        "shipping_date": shipping_info["shipping_date"]
                    },
                    "has_data": bool(shipping_info["order_id"] or shipping_info["recipient_name"])
                }
                results["debug_pages"].append(debug_page_info)
            else:
                # Use simple extraction without debug overhead
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
            print(f"Error processing page {page_num}: {e}")
            results["processing_status"] = "partial_success"
            
            if debug_mode:
                error_debug = {
                    "page_number": page_num,
                    "error": str(e),
                    "raw_ocr_text": "",
                    "has_data": False
                }
                results["debug_pages"].append(error_debug)
    
    return results

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
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
        
        try:
            # Process the PDF
            results = ocr_pdf_pages(filepath, max_pages, debug_mode=debug_mode)
            
            # Create base filename without extension
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
            
            # Create debug file if debug mode is enabled
            if debug_mode:
                debug_filename = f"debug_{base_filename}_{timestamp}.json"
                debug_path = create_debug_file(results, debug_filename)
                download_urls['debug'] = f'/download_debug/{debug_filename}'
            
            return jsonify({
                'success': True,
                'results': results,
                'download_urls': download_urls,
                'debug_mode': debug_mode
            })
            
        except Exception as e:
            return jsonify({'error': f'Processing failed: {str(e)}'}), 500
        
        finally:
            # Clean up uploaded file
            if os.path.exists(filepath):
                os.remove(filepath)
    
    return jsonify({'error': 'Invalid file type. Please upload a PDF file.'}), 400

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(RESULTS_FOLDER, filename), as_attachment=True)

@app.route('/download_debug/<filename>')
def download_debug_file(filename):
    return send_file(os.path.join(DEBUG_FOLDER, filename), as_attachment=True)

# Add health check endpoint for deployment platforms
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "platform": "render" if IS_RENDER else "railway" if IS_RAILWAY else "local",
        "environment": "production" if IS_PRODUCTION else "development"
    })

if __name__ == '__main__':
    # Production settings
    port = int(os.environ.get('PORT', 5000))
    debug = not IS_PRODUCTION
    app.run(host='0.0.0.0', port=port, debug=debug)