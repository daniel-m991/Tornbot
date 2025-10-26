import json
from datetime import datetime
from typing import Dict, List, Any, Tuple
import os

class LocalStorage:
    def __init__(self):
        """Initialize local storage with JSON files."""
        self.coverage_file = "coverage.json"
        self.transactions_file = "transactions.json"
        self._init_storage()

    def _init_storage(self):
        """Initialize storage files if they don't exist."""
        # Initialize coverage file
        if not os.path.exists(self.coverage_file):
            self._save_coverage([])
        
        # Initialize transactions file
        if not os.path.exists(self.transactions_file):
            self._save_transactions([])

    def _load_coverage(self) -> List[Dict]:
        """Load coverage data from JSON file."""
        try:
            with open(self.coverage_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_coverage(self, data: List[Dict]):
        """Save coverage data to JSON file."""
        with open(self.coverage_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def _load_transactions(self) -> List[Dict]:
        """Load transactions data from JSON file."""
        try:
            with open(self.transactions_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_transactions(self, data: List[Dict]):
        """Save transactions data to JSON file."""
        with open(self.transactions_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def add_coverage(self, order_data: Dict[str, Any]) -> bool:
        """Add new coverage entry."""
        try:
            coverage_list = self._load_coverage()
            
            # Create new coverage entry
            coverage_entry = {
                'order_id': order_data.get('order_id'),
                'user_id': order_data.get('user_id'),
                'username': order_data.get('username'),
                'coverage_type': order_data.get('coverage_type'),
                'duration': order_data.get('hours', order_data.get('jumps', 0)),
                'xanax_cost': order_data.get('xanax_payment', 0),
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'activated_at': None,
                'expires_at': None
            }
            
            coverage_list.append(coverage_entry)
            self._save_coverage(coverage_list)
            
            # Record payment transaction if any
            if order_data.get('xanax_payment', 0) > 0:
                self.record_transaction(
                    order_id=order_data.get('order_id'),
                    user_id=order_data.get('user_id'),
                    username=order_data.get('username'),
                    transaction_type='received',
                    amount=order_data.get('xanax_payment', 0),
                    notes=f"Coverage payment - {order_data.get('coverage_type')}"
                )
            
            return True
        except Exception as e:
            print(f"Error adding coverage: {e}")
            return False

    def activate_coverage(self, order_id: str) -> bool:
        """Activate coverage for an order."""
        try:
            coverage_list = self._load_coverage()
            
            for coverage in coverage_list:
                if coverage['order_id'] == order_id:
                    coverage['status'] = 'active'
                    coverage['activated_at'] = datetime.now().isoformat()
                    self._save_coverage(coverage_list)
                    return True
            
            return False
        except Exception as e:
            print(f"Error activating coverage: {e}")
            return False

    def record_transaction(self, order_id: str, user_id: int, username: str, 
                         transaction_type: str, amount: int, notes: str) -> bool:
        """Record a transaction."""
        try:
            transactions = self._load_transactions()
            
            transaction = {
                'order_id': order_id,
                'user_id': user_id,
                'username': username,
                'transaction_type': transaction_type,
                'amount': amount,
                'transaction_time': datetime.now().isoformat(),
                'notes': notes
            }
            
            transactions.append(transaction)
            self._save_transactions(transactions)
            return True
        except Exception as e:
            print(f"Error recording transaction: {e}")
            return False

    def get_stats(self) -> Tuple[int, int]:
        """Get total Xanax received and paid out."""
        try:
            transactions = self._load_transactions()
            
            total_received = sum(t['amount'] for t in transactions 
                               if t['transaction_type'] == 'received')
            total_paid = sum(t['amount'] for t in transactions 
                           if t['transaction_type'] == 'payout')
            
            return total_received, total_paid
        except Exception as e:
            print(f"Error getting stats: {e}")
            return 0, 0

    def get_user_stats(self, user_id: int) -> Tuple[int, int]:
        """Get total Xanax received and paid out for a specific user."""
        try:
            transactions = self._load_transactions()
            
            user_received = sum(t['amount'] for t in transactions 
                              if t['transaction_type'] == 'received' 
                              and t['user_id'] == user_id)
            user_paid = sum(t['amount'] for t in transactions 
                          if t['transaction_type'] == 'payout' 
                          and t['user_id'] == user_id)
            
            return user_received, user_paid
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return 0, 0

    def get_coverage_records(self, status: str = None, user_id: int = None, limit: int = 10) -> List[Dict]:
        """Get coverage records with optional filters."""
        try:
            coverage_list = self._load_coverage()
            
            # Apply filters
            if status:
                coverage_list = [c for c in coverage_list if c['status'] == status]
            if user_id:
                coverage_list = [c for c in coverage_list if c['user_id'] == user_id]
            
            # Sort by created_at in descending order
            coverage_list.sort(key=lambda x: x['created_at'], reverse=True)
            
            return coverage_list[:limit]
        except Exception as e:
            print(f"Error getting coverage records: {e}")
            return []

    def get_transaction_records(self, transaction_type: str = None, user_id: int = None, limit: int = 10) -> List[Dict]:
        """Get transaction records with optional filters."""
        try:
            transactions = self._load_transactions()
            
            # Apply filters
            if transaction_type:
                transactions = [t for t in transactions if t['transaction_type'] == transaction_type]
            if user_id:
                transactions = [t for t in transactions if t['user_id'] == user_id]
            
            # Sort by transaction_time in descending order
            transactions.sort(key=lambda x: x['transaction_time'], reverse=True)
            
            return transactions[:limit]
        except Exception as e:
            print(f"Error getting transaction records: {e}")
            return []

    def get_cost_analysis(self, days: int = None) -> Dict[str, Any]:
        """Get detailed cost analysis."""
        try:
            transactions = self._load_transactions()
            
            # Filter by days if specified
            if days:
                cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
                transactions = [t for t in transactions 
                              if datetime.fromisoformat(t['transaction_time']).timestamp() > cutoff_date]
            
            # Calculate received stats
            received_transactions = [t for t in transactions if t['transaction_type'] == 'received']
            received = {
                'total_transactions': len(received_transactions),
                'total_amount': sum(t['amount'] for t in received_transactions)
            }
            
            # Calculate paid stats
            paid_transactions = [t for t in transactions if t['transaction_type'] == 'payout']
            paid = {
                'total_transactions': len(paid_transactions),
                'total_amount': sum(t['amount'] for t in paid_transactions)
            }
            
            # Get top 5 payers
            user_payments = {}
            for t in received_transactions:
                uid = t['user_id']
                if uid not in user_payments:
                    user_payments[uid] = {'username': t['username'], 'total': 0, 'count': 0}
                user_payments[uid]['total'] += t['amount']
                user_payments[uid]['count'] += 1
            
            top_payers = sorted(
                [{'username': v['username'], 'transaction_count': v['count'], 'total_amount': v['total']} 
                 for v in user_payments.values()],
                key=lambda x: x['total_amount'],
                reverse=True
            )[:5]
            
            # Get top 5 receivers
            user_received = {}
            for t in paid_transactions:
                uid = t['user_id']
                if uid not in user_received:
                    user_received[uid] = {'username': t['username'], 'total': 0, 'count': 0}
                user_received[uid]['total'] += t['amount']
                user_received[uid]['count'] += 1
            
            top_receivers = sorted(
                [{'username': v['username'], 'transaction_count': v['count'], 'total_amount': v['total']} 
                 for v in user_received.values()],
                key=lambda x: x['total_amount'],
                reverse=True
            )[:5]
            
            return {
                'received': received,
                'paid': paid,
                'top_payers': top_payers,
                'top_receivers': top_receivers,
                'profit': received['total_amount'] - paid['total_amount'],
                'period_days': days
            }
            
        except Exception as e:
            print(f"Error getting cost analysis: {e}")
            return {}