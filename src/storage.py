import os
import csv
import json
import time
import sqlite3
import pandas as pd
from datetime import datetime
from loguru import logger
from pymongo import MongoClient
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, MetaData, Table
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

class StorageFactory:
    @staticmethod
    def get_storage(config):
        storage_type = config.get_storage_type()
        
        storage_classes = {
            "csv": CSVStorage,
            "json": JSONStorage,
            "mongodb": MongoDBStorage,
            "sqlite": SQLiteStorage
        }
        
        if storage_type not in storage_classes:
            logger.warning(f"Storage type {storage_type} not supported, falling back to CSV")
            storage_type = "csv"
            
        return storage_classes[storage_type](config)

class BaseStorage:
    def __init__(self, config):
        self.config = config
        
    def save(self, data):
        raise NotImplementedError("Subclasses must implement save method")
        
    def load(self):
        raise NotImplementedError("Subclasses must implement load method")
        
    def close(self):
        pass

class CSVStorage(BaseStorage):
    def __init__(self, config):
        super().__init__(config)
        self.file_path = config.get_storage_path()
        
    def save(self, data):
        """
        Save data to CSV file
        
        Args:
            data (list): List of dictionaries to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure data is a list of dictionaries
            if not isinstance(data, list):
                data = [data]
                
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
            
            # Check if file exists to determine if we need to write headers
            file_exists = os.path.isfile(self.file_path)
            
            # Flatten nested dictionaries
            flat_data = []
            for item in data:
                flat_item = {}
                for key, value in item.items():
                    if isinstance(value, dict):
                        for subkey, subvalue in value.items():
                            flat_item[f"{key}_{subkey}"] = subvalue
                    else:
                        flat_item[key] = value
                flat_data.append(flat_item)
                
            # Get all field names
            fieldnames = set()
            for item in flat_data:
                fieldnames.update(item.keys())
                
            # Write to CSV
            with open(self.file_path, 'a', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=list(fieldnames))
                
                if not file_exists:
                    writer.writeheader()
                    
                writer.writerows(flat_data)
                
            return True
            
        except Exception as e:
            logger.error(f"Error saving to CSV: {str(e)}")
            return False
            
    def load(self):
        """
        Load data from CSV file
        
        Returns:
            list: List of dictionaries
        """
        try:
            if not os.path.isfile(self.file_path):
                return []
                
            with open(self.file_path, 'r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                return list(reader)
                
        except Exception as e:
            logger.error(f"Error loading from CSV: {str(e)}")
            return []

class JSONStorage(BaseStorage):
    def __init__(self, config):
        super().__init__(config)
        self.file_path = config.get_storage_path().replace('.csv', '.json')
        
    def save(self, data):
        try:
            # Ensure data is a list
            if not isinstance(data, list):
                data = [data]
            
            # Format the data for better readability
            formatted_data = []
            for item in data:
                # Handle string content
                if isinstance(item, str):
                    formatted_item = {
                        'content': item,
                        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                    }
                else:
                    # Handle dictionary content
                    formatted_item = {
                        'url': item.get('url', ''),
                        'timestamp': item.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S')),
                        'data': item.get('data', {}),
                        'media': {
                            'images': [],
                            'videos': []
                        }
                    }
                    
                    # Format media data if present
                    media = item.get('media', {})
                    if media:
                        # Format image data
                        for img in media.get('images', []):
                            formatted_item['media']['images'].append({
                                'filename': img.get('filename'),
                                'original_url': img.get('original_url'),
                                'local_path': img.get('local_path'),
                                'size': self._format_size(img.get('size', 0))
                            })
                        
                        # Format video data
                        for vid in media.get('videos', []):
                            formatted_item['media']['videos'].append({
                                'filename': vid.get('filename'),
                                'original_url': vid.get('original_url'),
                                'local_path': vid.get('local_path'),
                                'size': self._format_size(vid.get('size', 0))
                            })
                
                formatted_data.append(formatted_item)
            
            # Save formatted data to file
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(formatted_data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Error saving data to JSON: {str(e)}")
            raise
    
    def _format_size(self, size_in_bytes):
        """Convert bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.1f} {unit}"
            size_in_bytes /= 1024.0
        return f"{size_in_bytes:.1f} TB"
    
    def load(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.error(f"Error loading data from JSON: {str(e)}")
            raise

class MongoDBStorage(BaseStorage):
    def __init__(self, config):
        super().__init__(config)
        self.db_config = config.get_database_config().get('mongodb', {})
        self.client = None
        self.db = None
        self.collection = None
        self._connect()
        
    def _connect(self):
        try:
            uri = self.db_config.get('uri', 'mongodb://localhost:27017')
            db_name = self.db_config.get('db_name', 'scraping_data')
            collection_name = self.db_config.get('collection', 'scraped_items')
            
            self.client = MongoClient(uri)
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            
        except Exception as e:
            logger.error(f"Error connecting to MongoDB: {str(e)}")
            
    def save(self, data):
        """
        Save data to MongoDB
        
        Args:
            data (list): List of dictionaries to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.collection:
                self._connect()
                if not self.collection:
                    return False
                    
            # Ensure data is a list of dictionaries
            if not isinstance(data, list):
                data = [data]
                
            # Add timestamp
            timestamp = datetime.now()
            for item in data:
                item['timestamp'] = timestamp
                
            # Insert data
            self.collection.insert_many(data)
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving to MongoDB: {str(e)}")
            return False
            
    def load(self, query=None, limit=None):
        """
        Load data from MongoDB
        
        Args:
            query (dict): Query filter
            limit (int): Maximum number of documents to return
            
        Returns:
            list: List of dictionaries
        """
        try:
            if not self.collection:
                self._connect()
                if not self.collection:
                    return []
                    
            if query is None:
                query = {}
                
            cursor = self.collection.find(query)
            
            if limit:
                cursor = cursor.limit(limit)
                
            # Convert ObjectId to string for JSON serialization
            result = []
            for doc in cursor:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                result.append(doc)
                
            return result
            
        except Exception as e:
            logger.error(f"Error loading from MongoDB: {str(e)}")
            return []
            
    def close(self):
        if self.client:
            self.client.close()

class SQLiteStorage(BaseStorage):
    def __init__(self, config):
        super().__init__(config)
        self.db_config = config.get_database_config().get('sqlite', {})
        self.file_path = self.db_config.get('path', 'scraping_data.db')
        self.table_name = self.db_config.get('table', 'scraped_items')
        self.engine = None
        self.session = None
        self.Base = declarative_base()
        self._connect()
        
    def _connect(self):
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
            
            # Connect to SQLite
            self.engine = create_engine(f'sqlite:///{self.file_path}')
            
            # Create dynamic table
            metadata = MetaData()
            self.table = Table(
                self.table_name, metadata,
                Column('id', Integer, primary_key=True),
                Column('url', String(500)),
                Column('title', String(500)),
                Column('content', Text),
                Column('timestamp', DateTime, default=datetime.now),
                Column('metadata', Text)  # JSON data as text
            )
            
            metadata.create_all(self.engine)
            
            # Create session
            Session = sessionmaker(bind=self.engine)
            self.session = Session()
            
        except Exception as e:
            logger.error(f"Error connecting to SQLite: {str(e)}")
            
    def save(self, data):
        """
        Save data to SQLite
        
        Args:
            data (list): List of dictionaries to save
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.engine or not self.session:
                self._connect()
                if not self.engine or not self.session:
                    return False
                    
            # Ensure data is a list of dictionaries
            if not isinstance(data, list):
                data = [data]
                
            # Prepare data for insertion
            timestamp = datetime.now()
            
            for item in data:
                # Extract common fields
                url = item.get('url', '')
                title = item.get('title', '')
                content = item.get('content', '')
                
                # Store rest as JSON
                metadata = {k: v for k, v in item.items() if k not in ['url', 'title', 'content']}
                metadata_json = json.dumps(metadata)
                
                # Insert into table
                self.engine.execute(
                    self.table.insert().values(
                        url=url,
                        title=title,
                        content=content,
                        timestamp=timestamp,
                        metadata=metadata_json
                    )
                )
                
            self.session.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving to SQLite: {str(e)}")
            if self.session:
                self.session.rollback()
            return False
            
    def load(self, query=None, limit=None):
        """
        Load data from SQLite
        
        Args:
            query (dict): Query filter
            limit (int): Maximum number of records to return
            
        Returns:
            list: List of dictionaries
        """
        try:
            if not self.engine:
                self._connect()
                if not self.engine:
                    return []
                    
            # Construct query
            select_query = self.table.select()
            
            if query:
                for key, value in query.items():
                    if key in ['url', 'title', 'content']:
                        select_query = select_query.where(getattr(self.table.c, key) == value)
                        
            if limit:
                select_query = select_query.limit(limit)
                
            # Execute query
            result_proxy = self.engine.execute(select_query)
            results = []
            
            for row in result_proxy:
                item = {
                    'id': row['id'],
                    'url': row['url'],
                    'title': row['title'],
                    'content': row['content'],
                    'timestamp': row['timestamp'].isoformat() if row['timestamp'] else None
                }
                
                # Parse metadata JSON
                if row['metadata']:
                    try:
                        metadata = json.loads(row['metadata'])
                        item.update(metadata)
                    except json.JSONDecodeError:
                        pass
                        
                results.append(item)
                
            return results
            
        except Exception as e:
            logger.error(f"Error loading from SQLite: {str(e)}")
            return []
            
    def close(self):
        if self.session:
            self.session.close()
        if self.engine:
            self.engine.dispose()