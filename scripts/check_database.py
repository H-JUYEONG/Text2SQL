"""
데이터베이스 데이터 확인 스크립트
생성된 데이터가 올바르게 들어갔는지 확인합니다.
"""
import sys
sys.dont_write_bytecode = True

import sqlite3
from src.config import DATABASE_URI


def check_database():
    """Check if database and data are correctly created."""
    db_path = DATABASE_URI.replace("sqlite:///", "")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=" * 70)
        print("📊 데이터베이스 확인")
        print("=" * 70)
        
        # 1. 테이블 목록 확인
        print("\n1️⃣ 테이블 목록:")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        for table in tables:
            print(f"   ✓ {table[0]}")
        
        if len(tables) != 4:
            print(f"   ⚠️  경고: 예상된 테이블 수는 4개인데 {len(tables)}개가 있습니다.")
        
        # 2. 각 테이블의 데이터 개수 확인
        print("\n2️⃣ 데이터 개수:")
        table_names = ["orders", "order_items", "drivers", "deliveries"]
        for table_name in table_names:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"   - {table_name}: {count}건")
            except sqlite3.OperationalError:
                print(f"   ✗ {table_name}: 테이블이 없습니다!")
        
        # 3. Orders 샘플 데이터 확인
        print("\n3️⃣ Orders 샘플 데이터 (최근 5건):")
        cursor.execute("""
            SELECT order_id, order_date, region 
            FROM orders 
            ORDER BY order_date DESC 
            LIMIT 5
        """)
        orders = cursor.fetchall()
        if orders:
            print("   order_id | order_date  | region")
            print("   " + "-" * 40)
            for order in orders:
                print(f"   {order[0]:8} | {order[1]} | {order[2]}")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        # 4. Drivers 확인
        print("\n4️⃣ 배송 기사 목록:")
        cursor.execute("SELECT driver_id, driver_name, vehicle_type FROM drivers")
        drivers = cursor.fetchall()
        if drivers:
            print("   driver_id | driver_name | vehicle_type")
            print("   " + "-" * 40)
            for driver in drivers:
                print(f"   {driver[0]:9} | {driver[1]:10} | {driver[2]}")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        # 5. 배송 상태 분포 확인
        print("\n5️⃣ 배송 상태 분포:")
        cursor.execute("""
            SELECT status, COUNT(*) as count,
                   ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM deliveries), 1) as percentage
            FROM deliveries
            GROUP BY status
            ORDER BY count DESC
        """)
        statuses = cursor.fetchall()
        if statuses:
            print("   status    | count | percentage")
            print("   " + "-" * 40)
            for status in statuses:
                print(f"   {status[0]:10} | {status[1]:5} | {status[2]:6}%")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        # 6. Order Items 샘플 확인
        print("\n6️⃣ Order Items 샘플 (최근 5건):")
        cursor.execute("""
            SELECT oi.order_item_id, oi.order_id, oi.product_name, 
                   oi.category, oi.weight_kg, oi.quantity
            FROM order_items oi
            ORDER BY oi.order_item_id DESC
            LIMIT 5
        """)
        items = cursor.fetchall()
        if items:
            print("   item_id | order_id | product_name | category | weight_kg | quantity")
            print("   " + "-" * 70)
            for item in items:
                print(f"   {item[0]:7} | {item[1]:8} | {item[2]:12} | {item[3]:8} | {item[4]:9.2f} | {item[5]:8}")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        # 7. JOIN 테스트 (권역별 배송 현황)
        print("\n7️⃣ 권역별 배송 현황 (JOIN 테스트):")
        cursor.execute("""
            SELECT o.region, 
                   COUNT(d.delivery_id) as total_deliveries,
                   SUM(CASE WHEN d.status = 'delivered' THEN 1 ELSE 0 END) as delivered,
                   SUM(CASE WHEN d.status = 'delayed' THEN 1 ELSE 0 END) as delayed
            FROM orders o
            LEFT JOIN deliveries d ON o.order_id = d.order_id
            GROUP BY o.region
            ORDER BY total_deliveries DESC
        """)
        regions = cursor.fetchall()
        if regions:
            print("   region  | total | delivered | delayed")
            print("   " + "-" * 40)
            for region in regions:
                print(f"   {region[0]:8} | {region[1]:5} | {region[2]:9} | {region[3]:7}")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        # 8. 기사별 처리량 확인
        print("\n8️⃣ 기사별 배송 처리량:")
        cursor.execute("""
            SELECT d.driver_name, 
                   COUNT(del.delivery_id) as delivery_count,
                   SUM(CASE WHEN del.status = 'delivered' THEN 1 ELSE 0 END) as completed
            FROM drivers d
            LEFT JOIN deliveries del ON d.driver_id = del.driver_id
            GROUP BY d.driver_id, d.driver_name
            ORDER BY delivery_count DESC
        """)
        driver_stats = cursor.fetchall()
        if driver_stats:
            print("   driver_name | total | completed")
            print("   " + "-" * 35)
            for stat in driver_stats:
                print(f"   {stat[0]:12} | {stat[1]:5} | {stat[2]:9}")
        else:
            print("   ✗ 데이터가 없습니다!")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ 데이터베이스 확인 완료!")
        print("=" * 70)
        
    except sqlite3.Error as e:
        print(f"\n❌ 데이터베이스 오류: {e}")
        print(f"   데이터베이스 파일 경로: {db_path}")
    except FileNotFoundError:
        print(f"\n❌ 데이터베이스 파일을 찾을 수 없습니다: {db_path}")
        print("   먼저 'python scripts/create_sample_db.py'를 실행하세요.")


if __name__ == "__main__":
    check_database()

