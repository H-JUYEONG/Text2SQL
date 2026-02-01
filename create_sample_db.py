"""
Create a sample logistics database for testing.
물류 회사 도메인에 맞는 데이터베이스 스키마 및 샘플 데이터 생성
"""
import sqlite3
from datetime import datetime, timedelta
import random


def create_sample_database(db_path: str = "logistics.db"):
    """Create a sample logistics database with test data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Drop existing tables if they exist (for clean recreation)
    cursor.execute("DROP TABLE IF EXISTS deliveries")
    cursor.execute("DROP TABLE IF EXISTS order_items")
    cursor.execute("DROP TABLE IF EXISTS orders")
    cursor.execute("DROP TABLE IF EXISTS drivers")
    
    # 1. Create orders table
    cursor.execute('''
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_date DATE NOT NULL,
            region VARCHAR(50) NOT NULL
        )
    ''')
    
    # 2. Create order_items table
    cursor.execute('''
        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            weight_kg FLOAT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    ''')
    
    # 3. Create drivers table
    cursor.execute('''
        CREATE TABLE drivers (
            driver_id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_name VARCHAR(50) NOT NULL,
            vehicle_type VARCHAR(30) NOT NULL
        )
    ''')
    
    # 4. Create deliveries table
    cursor.execute('''
        CREATE TABLE deliveries (
            delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            status VARCHAR(30) NOT NULL,
            shipped_at TIMESTAMP,
            delivered_at TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (driver_id) REFERENCES drivers(driver_id)
        )
    ''')
    
    # ========== Insert Sample Data ==========
    
    # Regions (권역)
    regions = ["수도권", "충청권", "경상권", "전라권", "강원권"]
    
    # Product categories
    categories = ["전자제품", "의류", "식품", "가구", "도서", "스포츠용품", "화장품"]
    
    # Product names by category
    products_by_category = {
        "전자제품": ["노트북", "스마트폰", "태블릿", "이어폰", "스피커"],
        "의류": ["티셔츠", "바지", "코트", "신발", "가방"],
        "식품": ["과자", "음료", "라면", "쌀", "과일"],
        "가구": ["책상", "의자", "침대", "소파", "수납장"],
        "도서": ["소설", "전문서적", "만화", "잡지", "교재"],
        "스포츠용품": ["운동화", "야구배트", "축구공", "자전거", "덤벨"],
        "화장품": ["립스틱", "파우더", "크림", "마스크", "선크림"]
    }
    
    # Driver names
    driver_names = ["김기사", "이기사", "박기사", "최기사", "정기사", "강기사", "조기사"]
    vehicle_types = ["truck", "van", "bike"]
    
    # ========== 1. Insert Drivers (5~8명) ==========
    num_drivers = random.randint(5, 8)
    driver_ids = []
    
    for i in range(num_drivers):
        driver_name = driver_names[i] if i < len(driver_names) else f"기사{i+1}"
        vehicle_type = random.choice(vehicle_types)
        
        cursor.execute('''
            INSERT INTO drivers (driver_name, vehicle_type)
            VALUES (?, ?)
        ''', (driver_name, vehicle_type))
        
        driver_ids.append(cursor.lastrowid)
    
    print(f"✓ Inserted {num_drivers} drivers")
    
    # ========== 2. Insert Orders (20~30건) ==========
    num_orders = random.randint(20, 30)
    order_ids = []
    base_date = datetime.now() - timedelta(days=30)
    
    for i in range(num_orders):
        order_date = base_date + timedelta(days=random.randint(0, 30))
        region = random.choice(regions)
        
        cursor.execute('''
            INSERT INTO orders (order_date, region)
            VALUES (?, ?)
        ''', (order_date.date(), region))
        
        order_ids.append(cursor.lastrowid)
    
    print(f"✓ Inserted {num_orders} orders")
    
    # ========== 3. Insert Order Items (주문당 1~3개, 총 40~60건) ==========
    total_items = 0
    
    for order_id in order_ids:
        num_items = random.randint(1, 3)
        
        for _ in range(num_items):
            category = random.choice(categories)
            product_name = random.choice(products_by_category[category])
            weight_kg = round(random.uniform(0.1, 50.0), 2)
            quantity = random.randint(1, 10)
            
            cursor.execute('''
                INSERT INTO order_items (order_id, product_name, category, weight_kg, quantity)
                VALUES (?, ?, ?, ?, ?)
            ''', (order_id, product_name, category, weight_kg, quantity))
            
            total_items += 1
    
    print(f"✓ Inserted {total_items} order items")
    
    # ========== 4. Insert Deliveries (orders와 1:1, 상태 분포 적용) ==========
    # 배송 상태 분포: delivered 60%, shipped 20%, delayed 15%, pending 5%
    status_weights = {
        "delivered": 0.60,
        "shipped": 0.20,
        "delayed": 0.15,
        "pending": 0.05
    }
    
    def get_status_by_weight():
        """가중치에 따라 상태 반환"""
        rand = random.random()
        cumulative = 0
        for status, weight in status_weights.items():
            cumulative += weight
            if rand <= cumulative:
                return status
        return "delivered"
    
    for order_id in order_ids:
        driver_id = random.choice(driver_ids)
        status = get_status_by_weight()
        
        # Find actual order date
        cursor.execute("SELECT order_date FROM orders WHERE order_id = ?", (order_id,))
        order_date_str = cursor.fetchone()[0]
        order_date_obj = datetime.strptime(order_date_str, "%Y-%m-%d")
        
        shipped_at = None
        delivered_at = None
        
        if status in ["shipped", "delivered", "delayed"]:
            shipped_at = order_date_obj + timedelta(days=random.randint(0, 3))
            
            if status == "delivered":
                # delivered_at: shipped_at 이후 1~5일
                delivered_at = shipped_at + timedelta(days=random.randint(1, 5))
            elif status == "delayed":
                # delayed: shipped_at 이후 6일 이상 (지연)
                delivered_at = None  # 아직 배송 안됨
        
        cursor.execute('''
            INSERT INTO deliveries (order_id, driver_id, status, shipped_at, delivered_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, driver_id, status, shipped_at, delivered_at))
    
    print(f"✓ Inserted {num_orders} deliveries")
    
    # ========== Commit and Close ==========
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 60)
    print(f"✅ Sample database created at: {db_path}")
    print("=" * 60)
    print("\n📊 Database Summary:")
    print(f"   - Orders: {num_orders}건")
    print(f"   - Order Items: {total_items}건")
    print(f"   - Drivers: {num_drivers}명")
    print(f"   - Deliveries: {num_orders}건")
    print("\n📋 Tables created:")
    print("   1. orders (주문 정보)")
    print("   2. order_items (주문 아이템)")
    print("   3. drivers (배송 기사)")
    print("   4. deliveries (배송 이력)")
    print("\n✅ Sample data inserted successfully!")


if __name__ == "__main__":
    create_sample_database()
