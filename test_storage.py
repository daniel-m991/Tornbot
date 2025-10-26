from storage import LocalStorage
from datetime import datetime

def test_local_storage():
    print("Testing Local Storage System")
    print("=" * 50)
    
    storage = LocalStorage()
    
    # Test adding coverage
    print("\n1. Testing coverage addition...")
    test_order = {
        'order_id': 'TEST_001',
        'user_id': 12345,
        'username': 'TestUser1',
        'coverage_type': 'time',
        'hours': 24,
        'xanax_payment': 5
    }
    
    success = storage.add_coverage(test_order)
    print(f"✓ Added test coverage: {success}")
    
    # Test activating coverage
    print("\n2. Testing coverage activation...")
    success = storage.activate_coverage('TEST_001')
    print(f"✓ Activated coverage: {success}")
    
    # Test recording a payout
    print("\n3. Testing payout recording...")
    success = storage.record_transaction(
        order_id='TEST_001',
        user_id=12345,
        username='TestUser1',
        transaction_type='payout',
        amount=10,
        notes='Test payout'
    )
    print(f"✓ Recorded payout: {success}")
    
    # Test getting stats
    print("\n4. Testing statistics retrieval...")
    received, paid = storage.get_stats()
    print(f"Total received: {received} Xanax")
    print(f"Total paid: {paid} Xanax")
    
    # Test getting user stats
    print("\n5. Testing user statistics...")
    user_received, user_paid = storage.get_user_stats(12345)
    print(f"User received: {user_received} Xanax")
    print(f"User paid: {user_paid} Xanax")
    
    # Test getting coverage records
    print("\n6. Testing coverage records retrieval...")
    records = storage.get_coverage_records()
    print(f"Found {len(records)} coverage records")
    for record in records:
        print(f"  - Order {record['order_id']}: {record['status']}")
    
    # Test getting transaction records
    print("\n7. Testing transaction records retrieval...")
    records = storage.get_transaction_records()
    print(f"Found {len(records)} transaction records")
    for record in records:
        print(f"  - {record['transaction_type']}: {record['amount']} Xanax")
    
    # Test cost analysis
    print("\n8. Testing cost analysis...")
    analysis = storage.get_cost_analysis(days=30)
    if analysis:
        print("Analysis results:")
        print(f"  Total received: {analysis['received']['total_amount']} Xanax")
        print(f"  Total paid: {analysis['paid']['total_amount']} Xanax")
        print(f"  Profit: {analysis['profit']} Xanax")
        if analysis['top_payers']:
            print("  Top payer:", analysis['top_payers'][0]['username'])
        if analysis['top_receivers']:
            print("  Top receiver:", analysis['top_receivers'][0]['username'])

if __name__ == "__main__":
    test_local_storage()