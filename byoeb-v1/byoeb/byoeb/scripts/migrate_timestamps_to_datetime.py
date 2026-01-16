#!/usr/bin/env python3
"""
MongoDB Timestamp Migration Script

Converts all timestamp fields from int/string to MongoDB datetime objects.

Usage:
    python migrate_timestamps_to_datetime.py \
        --connection-string "mongodb+srv://..." \
        --database ashadb \
        --collection ashausers \
        --dry-run  # Test without making changes
"""

import sys
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List
from collections import defaultdict

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, ConfigurationError
except ImportError:
    print("ERROR: pymongo is not installed. Please install it with:")
    print("  pip install pymongo")
    sys.exit(1)


class TimestampMigrator:
    """Migrates timestamp fields from int/string to datetime objects."""
    
    def __init__(self, connection_string: str, database: str, collection: str, dry_run: bool = False):
        self.connection_string = connection_string
        self.database_name = database
        self.collection_name = collection
        self.dry_run = dry_run
        self.client = None
        self.db = None
        self.collection = None
        self.stats = {
            'total_documents': 0,
            'documents_updated': 0,
            'documents_skipped': 0,
            'errors': 0,
            'fields_converted': defaultdict(int)
        }
    
    def connect(self):
        """Connect to MongoDB."""
        try:
            print(f"Connecting to MongoDB...")
            self.client = MongoClient(self.connection_string, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            print("[OK] Successfully connected to MongoDB")
            
            self.db = self.client[self.database_name]
            self.collection = self.db[self.collection_name]
            print(f"[OK] Connected to database: {self.database_name}")
            print(f"[OK] Using collection: {self.collection_name}")
            
        except ConnectionFailure as e:
            print(f"ERROR: Failed to connect to MongoDB: {e}")
            sys.exit(1)
        except ConfigurationError as e:
            print(f"ERROR: Invalid MongoDB connection string: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: Unexpected error connecting to MongoDB: {e}")
            sys.exit(1)
    
    def close(self):
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            print("\n[OK] Connection closed")
    
    def convert_to_datetime(self, value: Any) -> datetime:
        """Convert int or string timestamp to datetime object."""
        if isinstance(value, datetime):
            return value
        elif isinstance(value, int):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str):
            try:
                int_value = int(value)
                return datetime.fromtimestamp(int_value, tz=timezone.utc)
            except (ValueError, TypeError):
                raise ValueError(f"Cannot convert string '{value}' to datetime")
        else:
            raise ValueError(f"Cannot convert type {type(value)} to datetime")
    
    def migrate_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate a single document's timestamp fields."""
        updates = {}
        doc_id = doc.get("_id")
        
        # Migrate User.created_timestamp
        user_data = doc.get("User", {})
        if "created_timestamp" in user_data:
            value = user_data["created_timestamp"]
            if value is not None and not isinstance(value, datetime):
                try:
                    updates["User.created_timestamp"] = self.convert_to_datetime(value)
                    self.stats['fields_converted']['User.created_timestamp'] += 1
                except Exception as e:
                    print(f"  [WARNING] Error converting User.created_timestamp for {doc_id}: {e}")
                    self.stats['errors'] += 1
        
        # Migrate User.activity_timestamp
        if "activity_timestamp" in user_data:
            value = user_data["activity_timestamp"]
            if value is not None and not isinstance(value, datetime):
                try:
                    updates["User.activity_timestamp"] = self.convert_to_datetime(value)
                    self.stats['fields_converted']['User.activity_timestamp'] += 1
                except Exception as e:
                    print(f"  [WARNING] Error converting User.activity_timestamp for {doc_id}: {e}")
                    self.stats['errors'] += 1
        
        # Migrate document-level timestamp
        if "timestamp" in doc:
            value = doc["timestamp"]
            if value is not None and not isinstance(value, datetime):
                try:
                    updates["timestamp"] = self.convert_to_datetime(value)
                    self.stats['fields_converted']['timestamp'] += 1
                except Exception as e:
                    print(f"  [WARNING] Error converting timestamp for {doc_id}: {e}")
                    self.stats['errors'] += 1
        
        # Migrate last_conversations timestamps
        last_convs = user_data.get("last_conversations", [])
        if last_convs:
            updated_convs = []
            convs_changed = False
            for i, conv in enumerate(last_convs):
                if isinstance(conv, dict) and "timestamp" in conv:
                    value = conv["timestamp"]
                    if value is not None and not isinstance(value, datetime):
                        try:
                            updated_conv = conv.copy()
                            updated_conv["timestamp"] = self.convert_to_datetime(value)
                            updated_convs.append(updated_conv)
                            convs_changed = True
                            self.stats['fields_converted']['User.last_conversations[].timestamp'] += 1
                        except Exception as e:
                            print(f"  [WARNING] Error converting last_conversations[{i}].timestamp for {doc_id}: {e}")
                            updated_convs.append(conv)  # Keep original
                            self.stats['errors'] += 1
                    else:
                        updated_convs.append(conv)
                else:
                    updated_convs.append(conv)
            
            if convs_changed:
                updates["User.last_conversations"] = updated_convs
        
        return updates
    
    def migrate_collection(self, batch_size: int = 100):
        """Migrate all documents in the collection."""
        print(f"\n{'=' * 80}")
        print(f"MIGRATION MODE: {'DRY RUN (no changes will be made)' if self.dry_run else 'LIVE (changes will be saved)'}")
        print(f"{'=' * 80}\n")
        
        # Get total count
        self.stats['total_documents'] = self.collection.count_documents({})
        print(f"Total documents in collection: {self.stats['total_documents']}")
        
        if self.stats['total_documents'] == 0:
            print("WARNING: Collection is empty!")
            return
        
        # Process documents in batches
        processed = 0
        cursor = self.collection.find({})
        
        batch_updates = []
        
        for doc in cursor:
            processed += 1
            
            if processed % 100 == 0:
                print(f"  Processed {processed}/{self.stats['total_documents']} documents...", end='\r')
            
            updates = self.migrate_document(doc)
            
            if updates:
                doc_id = doc.get("_id")
                batch_updates.append({
                    "filter": {"_id": doc_id},
                    "update": {"$set": updates}
                })
                self.stats['documents_updated'] += 1
                
                # Execute batch when it reaches batch_size
                if len(batch_updates) >= batch_size:
                    if not self.dry_run:
                        self._execute_batch(batch_updates)
                    batch_updates = []
            else:
                self.stats['documents_skipped'] += 1
        
        # Execute remaining batch
        if batch_updates:
            if not self.dry_run:
                self._execute_batch(batch_updates)
        
        print(f"\n[OK] Processed {processed} documents")
    
    def _execute_batch(self, batch_updates: List[Dict[str, Any]]):
        """Execute a batch of updates."""
        try:
            from pymongo.operations import UpdateOne
            bulk_ops = []
            for update_op in batch_updates:
                bulk_ops.append(
                    UpdateOne(
                        update_op["filter"],
                        update_op["update"]
                    )
                )
            
            result = self.collection.bulk_write(bulk_ops)
            print(f"  [OK] Updated batch of {len(batch_updates)} documents")
        except Exception as e:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            print(f"  [WARNING] Error executing batch: {error_msg}")
            self.stats['errors'] += 1
    
    def print_summary(self):
        """Print migration summary."""
        print(f"\n{'=' * 80}")
        print("MIGRATION SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total documents: {self.stats['total_documents']}")
        print(f"Documents updated: {self.stats['documents_updated']}")
        print(f"Documents skipped: {self.stats['documents_skipped']}")
        print(f"Errors: {self.stats['errors']}")
        print(f"\nFields converted:")
        for field, count in self.stats['fields_converted'].items():
            print(f"  - {field}: {count}")
        print(f"\n{'=' * 80}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description='Migrate timestamp fields from int/string to datetime objects'
    )
    parser.add_argument(
        '--connection-string',
        '-c',
        type=str,
        required=True,
        help='MongoDB connection string'
    )
    parser.add_argument(
        '--database',
        '-d',
        type=str,
        default='ashadb',
        help='Database name (default: ashadb)'
    )
    parser.add_argument(
        '--collection',
        '-col',
        type=str,
        default='ashausers',
        help='Collection name (default: ashausers)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run migration in dry-run mode (no changes will be made)'
    )
    parser.add_argument(
        '--batch-size',
        '-b',
        type=int,
        default=100,
        help='Batch size for updates (default: 100)'
    )
    
    args = parser.parse_args()
    
    migrator = TimestampMigrator(
        connection_string=args.connection_string,
        database=args.database,
        collection=args.collection,
        dry_run=args.dry_run
    )
    
    try:
        migrator.connect()
        migrator.migrate_collection(batch_size=args.batch_size)
        migrator.print_summary()
    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        migrator.close()


if __name__ == '__main__':
    main()



