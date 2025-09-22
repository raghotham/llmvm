import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd
from datetime import datetime
from openai import OpenAI

class SemanticDatabaseHelpers:
    """
    Enhanced database helpers with semantic understanding using OpenAI Vector Stores.

    This class creates semantic representations of database schemas, table contents,
    and relationships, enabling natural language queries and intelligent suggestions.
    """

    # Class-level cache for schemas, business context, and vector store IDs
    _schema_cache = {}
    _business_context_cache = {}
    _vector_store_cache = {}
    _cache_dir = Path.home() / ".local/share/llmvm/semantic_database_cache"

    @classmethod
    def _ensure_cache_dir(cls):
        """Ensure the cache directory exists"""
        cls._cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _get_cache_key(cls, db_path: str) -> str:
        """Generate a cache key for a database path"""
        return f"{Path(db_path).resolve()}"

    @classmethod
    def _save_cache_to_disk(cls):
        """Save in-memory cache to disk for persistence"""
        cls._ensure_cache_dir()

        # Save schema cache
        schema_file = cls._cache_dir / "schemas.json"
        with open(schema_file, 'w') as f:
            json.dump(cls._schema_cache, f, indent=2)

        # Save business context cache
        context_file = cls._cache_dir / "business_context.json"
        with open(context_file, 'w') as f:
            json.dump(cls._business_context_cache, f, indent=2)

        # Save vector store cache
        vector_store_file = cls._cache_dir / "vector_stores.json"
        with open(vector_store_file, 'w') as f:
            json.dump(cls._vector_store_cache, f, indent=2)

    @classmethod
    def _load_cache_from_disk(cls):
        """Load cache from disk into memory"""
        cls._ensure_cache_dir()

        # Load schema cache
        schema_file = cls._cache_dir / "schemas.json"
        if schema_file.exists():
            with open(schema_file, 'r') as f:
                cls._schema_cache = json.load(f)

        # Load business context cache
        context_file = cls._cache_dir / "business_context.json"
        if context_file.exists():
            with open(context_file, 'r') as f:
                cls._business_context_cache = json.load(f)

        # Load vector store cache
        vector_store_file = cls._cache_dir / "vector_stores.json"
        if vector_store_file.exists():
            with open(vector_store_file, 'r') as f:
                cls._vector_store_cache = json.load(f)

    @classmethod
    def _get_openai_client(cls) -> OpenAI:
        """Get OpenAI client instance"""
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        return OpenAI(api_key=api_key)

    @staticmethod
    def create_semantic_understanding(db_path: str, force_refresh: bool = False) -> str:
        """
        Create semantic understanding of a database using OpenAI Vector Stores.

        This function:
        1. Analyzes database schema and relationships
        2. Extracts sample data and column meanings
        3. Creates rich semantic descriptions
        4. Uploads to OpenAI Vector Store for semantic search

        Example:
        result = SemanticDatabaseHelpers.create_semantic_understanding('./ecommerce.db')

        :param db_path: Path to the database file
        :param force_refresh: Force recreation of vector store even if cached
        :return: Status message with vector store information
        """
        # Load existing cache from disk
        SemanticDatabaseHelpers._load_cache_from_disk()
        cache_key = SemanticDatabaseHelpers._get_cache_key(db_path)

        # Check if we already have semantic understanding for this database
        if not force_refresh and cache_key in SemanticDatabaseHelpers._vector_store_cache:
            vector_store_id = SemanticDatabaseHelpers._vector_store_cache[cache_key]['vector_store_id']
            return f"Database semantic understanding already exists for {db_path}. Vector store ID: {vector_store_id}"

        try:
            client = SemanticDatabaseHelpers._get_openai_client()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get database name for vector store
            db_name = Path(db_path).stem

            # Analyze database structure
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

            # Create comprehensive semantic documentation
            semantic_docs = []

            # Database overview
            total_tables = len(tables)
            overview = f"""# Database: {db_name}

## Overview
This database contains {total_tables} tables and appears to be a {'business/ecommerce' if any(word in db_name.lower() for word in ['shop', 'store', 'ecommerce', 'commerce']) else 'data'} database.

## Tables and Structure
"""
            semantic_docs.append(overview)

            # Analyze each table in detail
            for table in tables:
                # Get column information
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()

                # Get foreign key information
                cursor.execute(f"PRAGMA foreign_key_list({table})")
                foreign_keys = cursor.fetchall()

                # Get sample data (first 5 rows)
                cursor.execute(f"SELECT * FROM {table} LIMIT 5")
                sample_rows = cursor.fetchall()

                # Get row count
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                row_count = cursor.fetchone()[0]

                # Create semantic description for this table
                table_doc = f"""
### Table: {table}
**Purpose**: {SemanticDatabaseHelpers._infer_table_purpose(table, columns)}
**Row Count**: {row_count}

#### Columns:
"""
                for col in columns:
                    col_name, col_type, not_null, default, pk = col[1], col[2], col[3], col[4], col[5]
                    purpose = SemanticDatabaseHelpers._infer_column_purpose(col_name, col_type)
                    table_doc += f"- **{col_name}** ({col_type}): {purpose}"
                    if pk:
                        table_doc += " [PRIMARY KEY]"
                    if not_null:
                        table_doc += " [NOT NULL]"
                    table_doc += "\n"

                # Add relationships
                if foreign_keys:
                    table_doc += "\n#### Relationships:\n"
                    for fk in foreign_keys:
                        table_doc += f"- {fk[3]} references {fk[2]}.{fk[4]}\n"

                # Add sample data analysis
                if sample_rows:
                    table_doc += f"\n#### Sample Data Patterns:\n"
                    table_doc += SemanticDatabaseHelpers._analyze_sample_data(columns, sample_rows)

                semantic_docs.append(table_doc)

            # Detect business domain and add domain-specific insights
            domain_analysis = SemanticDatabaseHelpers._analyze_business_domain(tables, semantic_docs)
            semantic_docs.append(f"\n## Business Domain Analysis\n{domain_analysis}")

            # Create a comprehensive semantic document
            full_semantic_doc = "\n".join(semantic_docs)

            # Create vector store and upload semantic understanding
            vector_store = client.beta.vector_stores.create(
                name=f"Semantic DB: {db_name}",
                expires_after={"anchor": "last_active_at", "days": 30}  # Auto-cleanup after 30 days
            )

            # Create temporary file with semantic documentation
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as temp_file:
                temp_file.write(full_semantic_doc)
                temp_file_path = temp_file.name

            try:
                # Upload file to vector store
                with open(temp_file_path, 'rb') as file_stream:
                    file_upload = client.files.create(
                        file=file_stream,
                        purpose='assistants'
                    )

                # Add file to vector store
                client.beta.vector_stores.files.create(
                    vector_store_id=vector_store.id,
                    file_id=file_upload.id
                )

                # Cache the vector store information
                SemanticDatabaseHelpers._vector_store_cache[cache_key] = {
                    'vector_store_id': vector_store.id,
                    'created_at': datetime.now().isoformat(),
                    'file_id': file_upload.id,
                    'db_name': db_name,
                    'tables': tables,
                    'semantic_doc_length': len(full_semantic_doc)
                }

                # Also update traditional cache
                SemanticDatabaseHelpers._schema_cache[cache_key] = {
                    'discovered_at': datetime.now().isoformat(),
                    'tables': {table: {'row_count': 0} for table in tables},  # Simplified for this version
                    'vector_store_id': vector_store.id
                }

                SemanticDatabaseHelpers._save_cache_to_disk()

                return f"""Semantic understanding created successfully for {db_path}

Vector Store ID: {vector_store.id}
Tables analyzed: {len(tables)}
Semantic document size: {len(full_semantic_doc)} characters
File ID: {file_upload.id}

The database semantic knowledge is now available for intelligent querying and analysis."""

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

            conn.close()

        except Exception as e:
            return f"Error creating semantic understanding for {db_path}: {str(e)}"

    @staticmethod
    def semantic_query(db_path: str, natural_language_query: str) -> str:
        """
        Query the database using natural language, leveraging semantic understanding.

        Example:
        result = SemanticDatabaseHelpers.semantic_query('./ecommerce.db',
                                                        'What are the top customers by revenue?')

        :param db_path: Path to the database file
        :param natural_language_query: Natural language question about the database
        :return: SQL query suggestions and analysis
        """
        SemanticDatabaseHelpers._load_cache_from_disk()
        cache_key = SemanticDatabaseHelpers._get_cache_key(db_path)

        if cache_key not in SemanticDatabaseHelpers._vector_store_cache:
            return "No semantic understanding found for this database. Run create_semantic_understanding() first."

        try:
            client = SemanticDatabaseHelpers._get_openai_client()
            vector_store_id = SemanticDatabaseHelpers._vector_store_cache[cache_key]['vector_store_id']

            # Create assistant with file search capabilities
            assistant = client.beta.assistants.create(
                name="Database Query Assistant",
                instructions="""You are an expert data analyst and SQL specialist. You have access to comprehensive semantic documentation about a database.

Your job is to:
1. Understand the user's natural language question
2. Analyze the database schema and relationships
3. Suggest appropriate SQL queries
4. Explain the reasoning behind your suggestions
5. Provide insights about what the query results might reveal

Always provide working SQL that can be executed against the database.""",
                model="gpt-4o",
                tools=[{"type": "file_search"}],
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
            )

            # Create thread and ask question
            thread = client.beta.threads.create()

            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=f"Based on the database schema and structure, help me with this query: {natural_language_query}"
            )

            # Run assistant
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant.id
            )

            # Wait for completion and get response
            import time
            while run.status in ['queued', 'in_progress']:
                time.sleep(1)
                run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

            # Get messages
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            response = messages.data[0].content[0].text.value

            # Cleanup
            client.beta.assistants.delete(assistant.id)

            return response

        except Exception as e:
            return f"Error processing semantic query: {str(e)}"

    @staticmethod
    def get_semantic_suggestions(db_path: str, context: str = "general analysis") -> List[str]:
        """
        Get intelligent suggestions for database analysis based on semantic understanding.

        Example:
        suggestions = SemanticDatabaseHelpers.get_semantic_suggestions('./ecommerce.db', 'revenue analysis')

        :param db_path: Path to the database file
        :param context: Context for suggestions (e.g., 'revenue analysis', 'customer insights')
        :return: List of suggested analyses and queries
        """
        result = SemanticDatabaseHelpers.semantic_query(
            db_path,
            f"Suggest 5-10 meaningful SQL queries for {context}. Focus on business insights and actionable metrics."
        )
        return [result]

    # Helper methods for semantic analysis
    @staticmethod
    def _infer_table_purpose(table_name: str, columns: List) -> str:
        """Infer the business purpose of a table based on name and columns"""
        name_lower = table_name.lower()
        col_names = [col[1].lower() for col in columns]

        if any(word in name_lower for word in ['user', 'customer', 'client']):
            return "Stores information about users/customers"
        elif any(word in name_lower for word in ['order', 'purchase', 'transaction']):
            return "Records sales transactions and orders"
        elif any(word in name_lower for word in ['product', 'item', 'inventory']):
            return "Manages product/inventory information"
        elif any(word in name_lower for word in ['payment', 'billing', 'invoice']):
            return "Handles payment and billing information"
        elif 'id' in col_names and len(col_names) > 3:
            return f"Main entity table for {table_name} with detailed attributes"
        else:
            return f"Data table for {table_name} operations"

    @staticmethod
    def _infer_column_purpose(col_name: str, col_type: str) -> str:
        """Infer the purpose of a column based on name and type"""
        name_lower = col_name.lower()

        if name_lower.endswith('_id') or name_lower == 'id':
            return "Unique identifier"
        elif 'email' in name_lower:
            return "Email address"
        elif 'name' in name_lower:
            return "Name/label field"
        elif 'date' in name_lower or 'time' in name_lower:
            return "Timestamp/date field"
        elif 'price' in name_lower or 'amount' in name_lower or 'cost' in name_lower:
            return "Monetary value"
        elif 'phone' in name_lower:
            return "Phone number"
        elif 'address' in name_lower:
            return "Address information"
        elif 'status' in name_lower:
            return "Status/state indicator"
        elif col_type.upper() in ['TEXT', 'VARCHAR']:
            return "Text/string data"
        elif col_type.upper() in ['INTEGER', 'INT']:
            return "Numeric value"
        elif col_type.upper() in ['REAL', 'DECIMAL', 'FLOAT']:
            return "Decimal/floating point number"
        else:
            return f"{col_type} field"

    @staticmethod
    def _analyze_sample_data(columns: List, sample_rows: List) -> str:
        """Analyze sample data to provide insights"""
        if not sample_rows:
            return "No sample data available"

        analysis = f"Sample of {len(sample_rows)} rows:\n"
        col_names = [col[1] for col in columns]

        # Look for patterns in the data
        for i, col_name in enumerate(col_names):
            values = [str(row[i]) if row[i] is not None else 'NULL' for row in sample_rows]
            unique_values = len(set(values))

            if unique_values == 1:
                analysis += f"  - {col_name}: Constant value ({values[0]})\n"
            elif unique_values == len(values):
                analysis += f"  - {col_name}: All unique values\n"
            else:
                analysis += f"  - {col_name}: {unique_values} unique values out of {len(values)}\n"

        return analysis

    @staticmethod
    def _analyze_business_domain(tables: List[str], semantic_docs: List[str]) -> str:
        """Analyze and determine the business domain of the database"""
        all_text = " ".join(tables + semantic_docs).lower()

        domains = {
            'ecommerce': ['order', 'customer', 'product', 'cart', 'payment', 'shipping'],
            'healthcare': ['patient', 'doctor', 'appointment', 'medical', 'treatment'],
            'education': ['student', 'course', 'grade', 'enrollment', 'teacher'],
            'finance': ['account', 'transaction', 'balance', 'loan', 'investment'],
            'hr': ['employee', 'department', 'salary', 'performance', 'attendance']
        }

        domain_scores = {}
        for domain, keywords in domains.items():
            score = sum(1 for keyword in keywords if keyword in all_text)
            if score > 0:
                domain_scores[domain] = score

        if domain_scores:
            primary_domain = max(domain_scores, key=domain_scores.get)
            return f"Primary domain: {primary_domain.title()} (confidence: {domain_scores[primary_domain]}/{len(domains[primary_domain])} keywords matched)"
        else:
            return "Domain: General purpose database"

    @staticmethod
    def clear_semantic_cache(db_path: Optional[str] = None) -> str:
        """
        Clear semantic understanding cache for a specific database or all databases.

        Example:
        SemanticDatabaseHelpers.clear_semantic_cache('./ecommerce.db')  # Clear specific database
        SemanticDatabaseHelpers.clear_semantic_cache()  # Clear all cached data

        :param db_path: Optional path to specific database, or None to clear all
        :return: Confirmation message
        """
        if db_path:
            cache_key = SemanticDatabaseHelpers._get_cache_key(db_path)
            SemanticDatabaseHelpers._schema_cache.pop(cache_key, None)
            SemanticDatabaseHelpers._business_context_cache.pop(cache_key, None)
            SemanticDatabaseHelpers._vector_store_cache.pop(cache_key, None)
            message = f"Cleared semantic cache for {db_path}"
        else:
            SemanticDatabaseHelpers._schema_cache.clear()
            SemanticDatabaseHelpers._business_context_cache.clear()
            SemanticDatabaseHelpers._vector_store_cache.clear()
            message = "Cleared all semantic database cache"

        SemanticDatabaseHelpers._save_cache_to_disk()
        return message