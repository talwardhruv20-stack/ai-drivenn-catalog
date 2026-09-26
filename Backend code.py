import os
import json
import subprocess
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
from mysql.connector import pooling

# ==========================================
# 1. DATABASE CONFIGURATION & CONNECTION POOL
# ==========================================
DB_CONFIG =  {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "1234",  # <-- CHANGE THIS
    "database": "ecommerce_ai_db",
    "pool_name": "ai_catalog_pool",
    "pool_size": 10
}

# Initialize MySQL Connection Pool
try:
    db_pool = mysql.connector.pooling.MySQLConnectionPool(**DB_CONFIG)
    print("✅ Successfully created MySQL connection pool.")
except mysql.connector.Error as err:
    print(f"❌ Error initializing MySQL Pool: {err}")
    db_pool = None

def get_db():
    """Dependency helper to get database connection from pool."""
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database connection pool unavailable")
    connection = db_pool.get_connection()
    try:
        yield connection
    finally:
        connection.close()

# ==========================================
# 2. FASTAPI APP & CORS FOR FRONTEND
# ==========================================
app = FastAPI(
    title="AI-Driven E-Commerce Catalog & Inventory API",
    version="1.0.0",
    description="Backend service integrating C++ image preprocessing, AI vision cataloging, and MySQL storage."
)

# Enable CORS so HTML/JS frontend can fetch data without cross-origin errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust to specific domains in production (e.g., http://localhost:3000)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 3. PYDANTIC SCHEMAS
# ==========================================
class ProductCreate(BaseModel):
    title: str
    description: str
    category: str
    price: float
    current_stock: int
    reorder_level: int
    seo_tags: List[str]

class PurchaseOrderCreate(BaseModel):
    product_id: int
    supplier_id: int
    order_quantity: int

# ==========================================
# 4. HELPER FUNCTIONS (C++ & AI SIMULATION)
# ==========================================
def preprocess_image_cpp(input_path: str, output_path: str) -> bool:
    """Executes native compiled C++ binary for high-speed image preprocessing."""
    try:
        # Assuming compiled binary executable 'cpp_processor' exists
        result = subprocess.run(
            ["./cpp_processor", input_path, output_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        print(f"⚠️ C++ Preprocessing fallback used: {e}")
        return False

def generate_ai_metadata(image_filename: str):
    """
    Simulates calling Gemini API or Vision AI model to extract tags and SEO descriptions.
    In production, replace this with actual Gemini API SDK call.
    """
    cleaned_name = os.path.splitext(image_filename)[0].replace("_", " ").title()
    return {
        "title": f"AI Optimized {cleaned_name}",
        "seo_description": f"High-quality {cleaned_name} built for modern commercial environments. Durable, ergonomic, and top-rated.",
        "category": "Office & Workspace",
        "price": 149.99,
        "suggested_tags": [cleaned_name.lower(), "commercial", "top-tier", "best-seller"]
    }

# ==========================================
# 5. REST API ENDPOINTS FOR FRONTEND
# ==========================================

@app.get("/")
def read_root():
    return {"message": "AI Catalog & Inventory Backend API is active"}

# --- ENDPOINT 1: Upload Raw Image & Process via C++ / AI / MySQL ---
@app.post("/api/upload-image")
async def upload_product_image(
    file: UploadFile = File(...),
    db = Depends(get_db)
):
    upload_dir = "./uploads"
    os.makedirs(upload_dir, exist_ok=True)
    raw_file_path = os.path.join(upload_dir, file.filename)
    processed_file_path = os.path.join(upload_dir, f"proc_{file.filename}")

    # Save incoming image
    with open(raw_file_path, "wb") as buffer:
        buffer.write(await file.read())

    # 1. High-speed C++ preprocessing
    cpp_success = preprocess_image_cpp(raw_file_path, processed_file_path)

    # 2. AI Multimodal Generation (Tagging & SEO)
    ai_metadata = generate_ai_metadata(file.filename)

    # 3. Database Insertion via MySQL Connector
    cursor = db.cursor(dictionary=True)
    sku_code = f"SKU-{int(datetime.now().timestamp())}"
    
    insert_query = """
        INSERT INTO products 
        (sku, title, seo_description, category, price, current_stock, reorder_level, image_url, raw_tags, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    values = (
        sku_code,
        ai_metadata["title"],
        ai_metadata["seo_description"],
        ai_metadata["category"],
        ai_metadata["price"],
        25,  # initial default stock
        10,  # initial reorder threshold
        processed_file_path if cpp_success else raw_file_path,
        json.dumps(ai_metadata["suggested_tags"]),
        "SYNCED"
    )

    try:
        cursor.execute(insert_query, values)
        db.commit()
        product_id = cursor.lastrowid
        cursor.close()

        return {
            "success": True,
            "product_id": product_id,
            "sku": sku_code,
            "cpp_processed": cpp_success,
            "ai_metadata": ai_metadata
        }
    except mysql.connector.Error as err:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database Insertion Error: {err}")

# --- ENDPOINT 2: Fetch Dynamic Catalog Listing ---
@app.get("/api/catalog")
def get_catalog(db = Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    query = """
        SELECT id, sku, title, seo_description, category, price, current_stock, reorder_level, status, created_at 
        FROM products 
        ORDER BY id DESC
    """
    cursor.execute(query)
    products = cursor.fetchall()
    cursor.close()
    return {"products": products}

# --- ENDPOINT 3: ML Inventory Restock Velocity Predictions ---
@app.get("/api/inventory/predictions")
def get_inventory_predictions(db = Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    query = """
        SELECT p.id, p.sku, p.title, p.current_stock, p.reorder_level,
               COALESCE(SUM(s.quantity_sold), 0) as total_units_sold_30d
        FROM products p
        LEFT JOIN sales_history s ON p.id = s.product_id 
             AND s.sale_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        GROUP BY p.id
    """
    cursor.execute(query)
    items = cursor.fetchall()
    cursor.close()

    predictions = []
    for item in items:
        # Calculate daily sales velocity
        daily_velocity = item["total_units_sold_30d"] / 30.0 if item["total_units_sold_30d"] > 0 else 0.5
        days_until_out = int(item["current_stock"] / daily_velocity)
        predicted_date = datetime.now() + timedelta(days=days_until_out)

        predictions.append({
            "product_id": item["id"],
            "title": item["title"],
            "current_stock": item["current_stock"],
            "daily_velocity": round(daily_velocity, 2),
            "days_remaining": days_until_out,
            "predicted_out_of_stock_date": predicted_date.strftime("%Y-%m-%d"),
            "needs_restock": item["current_stock"] <= item["reorder_level"] or days_until_out <= 7
        })

    return {"predictions": predictions}

# --- ENDPOINT 4: Automated Purchase Order Creation ---
@app.post("/api/trigger-po")
def trigger_purchase_order(po: PurchaseOrderCreate, db = Depends(get_db)):
    cursor = db.cursor(dictionary=True)
    insert_query = """
        INSERT INTO purchase_orders (product_id, supplier_id, order_quantity, status)
        VALUES (%s, %s, %s, 'ORDERED')
    """
    try:
        cursor.execute(insert_query, (po.product_id, po.supplier_id, po.order_quantity))
        
        # Update product status to indicate reorder in progress
        update_query = "UPDATE products SET status = 'REORDER_TRIGGERED' WHERE id = %s"
        cursor.execute(update_query, (po.product_id,))
        
        db.commit()
        po_id = cursor.lastrowid
        cursor.close()
        
        return {
            "success": True,
            "po_id": po_id,
            "message": f"Automated Purchase Order #{po_id} created for Product #{po.product_id}"
        }
    except mysql.connector.Error as err:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create Purchase Order: {err}")

# ==========================================
# 6. RUNNER INSTRUCTION
# ==========================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("Backend code:app", host="127.0.0.1", port=8005, reload=False) 
