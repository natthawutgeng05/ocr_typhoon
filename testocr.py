import os
import json
import re
from openai import OpenAI
from typhoon_ocr import ocr_document
import PyPDF2

# Set the API key as environment variable
os.environ["TYPHOON_OCR_API_KEY"] = "sk-6wAULZZYCQTVHb5GW4XBcYznTStuxDJAdSBeHLH4mFsSfL42"

def get_pdf_page_count(pdf_path):
    """Get the total number of pages in a PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            return len(pdf_reader.pages)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return 1  # Default to 1 page if error

def extract_shipping_info(text):
    """Extract specific shipping information from OCR text"""
    extracted_data = {
        "recipient_name": "",
        "recipient_address": "",
        "order_id": "",
        "shipping_date": ""
    }
    
    # Extract recipient info (ถึง) with improved pattern
    recipient_pattern = r'ถึง\s+(.+?)(?:\n|\r)(.+?)(?:\n|\r)'
    recipient_match = re.search(recipient_pattern, text, re.IGNORECASE | re.DOTALL)
    
    if recipient_match:
        # First line after "ถึง" is the name
        extracted_data["recipient_name"] = recipient_match.group(1).strip()
        # Second line is the address
        extracted_data["recipient_address"] = recipient_match.group(2).strip()
    else:
        # Fallback: try to extract just the name
        name_match = re.search(r'ถึง\s+(.+?)(?:\n|\r)', text, re.IGNORECASE)
        if name_match:
            extracted_data["recipient_name"] = name_match.group(1).strip()
    
    # Extract Order ID
    order_id_match = re.search(r'Order ID\s*\n?(\d+)', text, re.IGNORECASE)
    if order_id_match:
        extracted_data["order_id"] = order_id_match.group(1).strip()
    
    # Extract Shipping Date
    shipping_date_match = re.search(r'Shipping Date:\s*\n?(.+?)(?:\n|\r)', text, re.IGNORECASE)
    if shipping_date_match:
        extracted_data["shipping_date"] = shipping_date_match.group(1).strip()
    
    return extracted_data

def ocr_limited_pages(pdf_path, max_pages=5, task_type="default"):
    """OCR limited pages of a PDF and extract shipping information"""
    
    # Get total pages
    total_pages = get_pdf_page_count(pdf_path)
    pages_to_process = min(max_pages, total_pages)
    
    print(f"Total pages: {total_pages}, Processing first {pages_to_process} pages...")
    
    results = {
        "document": pdf_path,
        "total_pages": total_pages,
        "processed_pages": pages_to_process,
        "extracted_orders": []
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
            
            # Extract shipping info
            shipping_info = extract_shipping_info(markdown)
            
            page_result = {
                "page_number": page_num,
                "raw_content": markdown,
                "extracted_data": shipping_info,
                "status": "success"
            }
            
            # Only add to extracted_orders if we found relevant data
            if shipping_info["order_id"] or shipping_info["recipient_name"]:
                results["extracted_orders"].append({
                    "page": page_num,
                    "recipient_name": shipping_info["recipient_name"],
                    "recipient_address": shipping_info["recipient_address"],
                    "order_id": shipping_info["order_id"],
                    "shipping_date": shipping_info["shipping_date"]
                })
            
        except Exception as e:
            page_result = {
                "page_number": page_num,
                "raw_content": "",
                "extracted_data": {},
                "status": "error",
                "error": str(e)
            }
            print(f"Error processing page {page_num}: {e}")
        
        # Add to results for debugging
        if "pages" not in results:
            results["pages"] = []
        results["pages"].append(page_result)
    
    return results

# Initialize the client with your API key and the OpenTyphoon base URL
client = OpenAI(
    api_key="sk-6wAULZZYCQTVHb5GW4XBcYznTStuxDJAdSBeHLH4mFsSfL42",
    base_url="https://api.opentyphoon.ai/v1"
)

# OCR limited pages
pdf_file = "10.6.25-118 Order บ่าย.pdf"
all_results = ocr_limited_pages(pdf_file, max_pages=5)

# Print extracted orders only
print("\n" + "="*50)
print("EXTRACTED SHIPPING INFORMATION:")
print("="*50)

for order in all_results["extracted_orders"]:
    print(f"\n--- Page {order['page']} ---")
    print(f"ชื่อผู้รับ: {order['recipient_name']}")
    print(f"ที่อยู่: {order['recipient_address']}")
    print(f"Order ID: {order['order_id']}")
    print(f"Shipping Date: {order['shipping_date']}")
    print("-" * 30)

# Save to file
output_file = "extracted_orders.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print(f"\nResults saved to {output_file}")

# Save just the clean extracted data
clean_output_file = "clean_orders.json"
clean_data = {
    "document": all_results["document"],
    "processed_pages": all_results["processed_pages"],
    "orders": all_results["extracted_orders"]
}

with open(clean_output_file, 'w', encoding='utf-8') as f:
    json.dump(clean_data, f, ensure_ascii=False, indent=2)

print(f"Clean data saved to {clean_output_file}")