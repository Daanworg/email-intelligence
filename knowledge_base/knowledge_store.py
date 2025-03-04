"""
Knowledge store for the Email Intelligence System.
Manages the storage and retrieval of entities and relationships.
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from google.cloud import storage, bigquery
import faiss


class KnowledgeStore:
    """Manages entity and relationship storage for the knowledge base."""
    
    def __init__(
        self,
        project_id: str,
        bucket_name: str,
        vector_dimension: int = 768,
        local_index_path: str = "/tmp/knowledge_index"
    ):
        """Initialize the knowledge store.
        
        Args:
            project_id: Google Cloud project ID
            bucket_name: Cloud Storage bucket for storing knowledge
            vector_dimension: Dimension of entity embeddings
            local_index_path: Path to store FAISS index locally
        """
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.vector_dimension = vector_dimension
        self.local_index_path = local_index_path
        
        # Initialize clients
        self.storage_client = storage.Client(project=project_id)
        self.bq_client = bigquery.Client(project=project_id)
        
        # Initialize or load the FAISS index
        self.index = self._initialize_index()
        
        # Entity and relationship maps for in-memory operations
        self.entity_map = {}  # entity_id -> entity
        self.entity_id_map = {}  # (text, type) -> entity_id
        self.relationship_map = {}  # relationship_id -> relationship
    
    def _initialize_index(self) -> faiss.Index:
        """Initialize or load the FAISS index.
        
        Returns:
            FAISS index
        """
        # Check if we have a local index file
        local_file = f"{self.local_index_path}.index"
        
        if os.path.exists(local_file):
            print(f"Loading existing FAISS index from {local_file}")
            index = faiss.read_index(local_file)
        else:
            print(f"Creating new FAISS index with dimension {self.vector_dimension}")
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(local_file), exist_ok=True)
            
            # Create a new index
            index = faiss.IndexFlatL2(self.vector_dimension)
            
            # Try to load existing index from Cloud Storage
            try:
                self._load_index_from_storage(index)
            except Exception as e:
                print(f"Could not load index from storage: {e}")
        
        return index
    
    def _load_index_from_storage(self, index: faiss.Index) -> None:
        """Load index from Cloud Storage.
        
        Args:
            index: FAISS index to update
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob("knowledge/index.faiss")
        
        if blob.exists():
            print(f"Loading index from Cloud Storage: gs://{self.bucket_name}/knowledge/index.faiss")
            
            # Download to temp file
            local_file = f"{self.local_index_path}_temp.index"
            blob.download_to_filename(local_file)
            
            # Load the index
            loaded_index = faiss.read_index(local_file)
            
            # Copy data to our index
            if loaded_index.ntotal > 0:
                # Create a new index with the same data
                index = loaded_index
            
            # Clean up temp file
            os.remove(local_file)
    
    def _save_index_to_storage(self) -> None:
        """Save index to Cloud Storage."""
        if self.index.ntotal > 0:
            local_file = f"{self.local_index_path}.index"
            
            # Save to local file first
            faiss.write_index(self.index, local_file)
            
            # Upload to Cloud Storage
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob("knowledge/index.faiss")
            
            blob.upload_from_filename(local_file)
            print(f"Saved index with {self.index.ntotal} vectors to gs://{self.bucket_name}/knowledge/index.faiss")
    
    def add_entities(self, entities: List[Dict[str, Any]]) -> List[str]:
        """Add entities to the knowledge store.
        
        Args:
            entities: List of entity dictionaries
            
        Returns:
            List of entity IDs
        """
        if not entities:
            return []
        
        entity_ids = []
        vectors_to_add = []
        vector_ids = []
        
        for entity in entities:
            entity_id = entity.get("entity_id")
            if not entity_id:
                # Generate a new ID if none provided
                entity_id = str(uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{entity['text'].lower()}-{entity['type']}"
                ))
                entity["entity_id"] = entity_id
            
            # Check if entity already exists
            existing_entity = self.entity_map.get(entity_id)
            
            if existing_entity:
                # Update existing entity
                # Merge source documents
                source_docs = set(existing_entity.get("source_documents", []))
                source_docs.update(entity.get("source_documents", []))
                existing_entity["source_documents"] = list(source_docs)
                
                # Update other fields if provided
                for key, value in entity.items():
                    if key != "entity_id" and key != "source_documents" and key != "embedding":
                        existing_entity[key] = value
                
                # Only update embedding if provided
                if "embedding" in entity:
                    existing_entity["embedding"] = entity["embedding"]
                    
                    # Update index
                    # This is a simplified approach - in production you'd need to track
                    # the index position and use remove/add operations or re-index
                    existing_id = self.entity_id_map.get((entity["text"].lower(), entity["type"]))
                    if existing_id is not None:
                        vector_ids.append(existing_id)
                        vectors_to_add.append(entity["embedding"])
                
                entity_ids.append(entity_id)
            else:
                # Add new entity
                self.entity_map[entity_id] = entity
                self.entity_id_map[(entity["text"].lower(), entity["type"])] = len(self.entity_id_map)
                
                # Add to list for batch index update
                if "embedding" in entity:
                    vector_ids.append(self.entity_id_map[(entity["text"].lower(), entity["type"])])
                    vectors_to_add.append(entity["embedding"])
                
                entity_ids.append(entity_id)
        
        # Update FAISS index
        if vectors_to_add:
            vectors_array = np.array(vectors_to_add).astype('float32')
            
            if self.index.ntotal == 0:
                # First-time addition
                self.index.add(vectors_array)
            else:
                # Add to existing index
                self.index.add(vectors_array)
            
            # Save updated index
            self._save_index_to_storage()
        
        # Save entities to Storage
        self._save_entities_to_storage(entities)
        
        return entity_ids
    
    def add_relationships(self, relationships: List[Dict[str, Any]]) -> List[str]:
        """Add relationships to the knowledge store.
        
        Args:
            relationships: List of relationship dictionaries
            
        Returns:
            List of relationship IDs
        """
        if not relationships:
            return []
        
        relationship_ids = []
        
        for relationship in relationships:
            rel_id = relationship.get("relationship_id")
            if not rel_id:
                rel_id = str(uuid.uuid4())
                relationship["relationship_id"] = rel_id
            
            # Check for duplicate relationships
            is_duplicate = False
            for existing_id, existing_rel in self.relationship_map.items():
                if (existing_rel["source_entity_id"] == relationship["source_entity_id"] and
                    existing_rel["target_entity_id"] == relationship["target_entity_id"] and
                    existing_rel["relationship_type"] == relationship["relationship_type"]):
                    
                    # Update confidence if new one is higher
                    if relationship.get("confidence", 0) > existing_rel.get("confidence", 0):
                        existing_rel["confidence"] = relationship["confidence"]
                    
                    relationship_ids.append(existing_id)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                self.relationship_map[rel_id] = relationship
                relationship_ids.append(rel_id)
        
        # Save relationships to Storage
        self._save_relationships_to_storage(relationships)
        
        return relationship_ids
    
    def search_entities(
        self,
        query_embedding: List[float] = None,
        query_text: str = None,
        entity_type: str = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for entities based on embedding similarity or text query.
        
        Args:
            query_embedding: Vector embedding to search with
            query_text: Text to search for
            entity_type: Optional filter by entity type
            top_k: Number of results to return
            
        Returns:
            List of entity dictionaries with similarity scores
        """
        if query_embedding is None and query_text is None:
            raise ValueError("Either query_embedding or query_text must be provided")
        
        if query_embedding is not None:
            # Vector search
            return self._search_by_vector(query_embedding, entity_type, top_k)
        else:
            # Text search
            return self._search_by_text(query_text, entity_type, top_k)
    
    def _search_by_vector(
        self,
        query_embedding: List[float],
        entity_type: str = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search entities by vector similarity.
        
        Args:
            query_embedding: Vector embedding to search with
            entity_type: Optional filter by entity type
            top_k: Number of results to return
            
        Returns:
            List of entity dictionaries with similarity scores
        """
        if self.index.ntotal == 0:
            return []
        
        # Convert embedding to numpy array
        query_vector = np.array([query_embedding]).astype('float32')
        
        # Search the index
        distances, indices = self.index.search(query_vector, top_k * 3)  # Get more to allow for filtering
        
        # Collect results
        results = []
        
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx != -1:  # Valid result
                # Find the entity corresponding to this index
                found_entity = None
                found_key = None
                
                for key, entity_idx in self.entity_id_map.items():
                    if entity_idx == idx:
                        found_key = key
                        break
                
                if found_key:
                    text, etype = found_key
                    
                    # Filter by entity type if requested
                    if entity_type and etype != entity_type:
                        continue
                    
                    # Find the entity ID
                    for eid, entity in self.entity_map.items():
                        if entity["text"].lower() == text and entity["type"] == etype:
                            found_entity = entity
                            break
                
                if found_entity:
                    # Add similarity score
                    similarity = 1.0 / (1.0 + distance)  # Convert distance to similarity
                    entity_copy = found_entity.copy()
                    entity_copy["similarity"] = similarity
                    
                    results.append(entity_copy)
                    
                    # Stop if we have enough results
                    if len(results) >= top_k:
                        break
        
        return results
    
    def _search_by_text(
        self,
        query_text: str,
        entity_type: str = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search entities by text matching.
        
        Args:
            query_text: Text to search for
            entity_type: Optional filter by entity type
            top_k: Number of results to return
            
        Returns:
            List of entity dictionaries with match scores
        """
        # Simple text matching for now
        results = []
        
        query_lower = query_text.lower()
        
        for entity_id, entity in self.entity_map.items():
            # Filter by entity type if requested
            if entity_type and entity["type"] != entity_type:
                continue
            
            # Calculate a simple match score
            entity_text = entity["text"].lower()
            
            if query_lower == entity_text:
                # Exact match
                match_score = 1.0
            elif query_lower in entity_text or entity_text in query_lower:
                # Partial match
                match_score = 0.8
            else:
                # Check for word overlaps
                query_words = set(query_lower.split())
                entity_words = set(entity_text.split())
                
                # Jaccard similarity of words
                if query_words and entity_words:
                    intersection = query_words.intersection(entity_words)
                    union = query_words.union(entity_words)
                    match_score = len(intersection) / len(union)
                else:
                    match_score = 0.0
            
            if match_score > 0.1:  # Threshold for including in results
                entity_copy = entity.copy()
                entity_copy["similarity"] = match_score
                results.append(entity_copy)
        
        # Sort by score and limit results
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
    
    def get_entity_relationships(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all relationships for an entity.
        
        Args:
            entity_id: Entity ID to get relationships for
            
        Returns:
            List of relationship dictionaries
        """
        relationships = []
        
        for rel_id, relationship in self.relationship_map.items():
            if relationship["source_entity_id"] == entity_id or relationship["target_entity_id"] == entity_id:
                relationships.append(relationship)
        
        return relationships
    
    def get_entity_by_id(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get entity by ID.
        
        Args:
            entity_id: Entity ID
            
        Returns:
            Entity dictionary or None if not found
        """
        return self.entity_map.get(entity_id)
    
    def _save_entities_to_storage(self, entities: List[Dict[str, Any]]) -> None:
        """Save entities to Cloud Storage.
        
        Args:
            entities: List of entity dictionaries
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        
        for entity in entities:
            # Create a copy for storage to avoid modifying original
            storage_entity = entity.copy()
            
            # Convert embeddings to list for JSON serialization
            if "embedding" in storage_entity and not isinstance(storage_entity["embedding"], list):
                storage_entity["embedding"] = storage_entity["embedding"].tolist()
            
            # Save to Cloud Storage
            entity_id = storage_entity["entity_id"]
            entity_type = storage_entity["type"]
            
            blob = bucket.blob(f"knowledge/entities/{entity_type}/{entity_id}.json")
            blob.upload_from_string(
                json.dumps(storage_entity, indent=2),
                content_type="application/json"
            )
    
    def _save_relationships_to_storage(self, relationships: List[Dict[str, Any]]) -> None:
        """Save relationships to Cloud Storage.
        
        Args:
            relationships: List of relationship dictionaries
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        
        for relationship in relationships:
            # Save to Cloud Storage
            rel_id = relationship["relationship_id"]
            rel_type = relationship["relationship_type"]
            
            blob = bucket.blob(f"knowledge/relationships/{rel_type}/{rel_id}.json")
            blob.upload_from_string(
                json.dumps(relationship, indent=2),
                content_type="application/json"
            )
    
    def load_all_from_storage(self) -> Tuple[int, int]:
        """Load all entities and relationships from storage.
        
        Returns:
            Tuple of (entity_count, relationship_count)
        """
        # Load entities
        entity_count = self._load_entities_from_storage()
        
        # Load relationships
        relationship_count = self._load_relationships_from_storage()
        
        return entity_count, relationship_count
    
    def _load_entities_from_storage(self) -> int:
        """Load entities from Cloud Storage.
        
        Returns:
            Number of entities loaded
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        entity_count = 0
        
        for blob in bucket.list_blobs(prefix="knowledge/entities/"):
            if blob.name.endswith(".json"):
                try:
                    # Load entity from storage
                    entity_data = json.loads(blob.download_as_string())
                    
                    # Add to in-memory store
                    entity_id = entity_data["entity_id"]
                    self.entity_map[entity_id] = entity_data
                    
                    # Add to ID map for indexing
                    self.entity_id_map[(entity_data["text"].lower(), entity_data["type"])] = len(self.entity_id_map)
                    
                    entity_count += 1
                except Exception as e:
                    print(f"Error loading entity {blob.name}: {e}")
        
        print(f"Loaded {entity_count} entities from storage")
        return entity_count
    
    def _load_relationships_from_storage(self) -> int:
        """Load relationships from Cloud Storage.
        
        Returns:
            Number of relationships loaded
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        relationship_count = 0
        
        for blob in bucket.list_blobs(prefix="knowledge/relationships/"):
            if blob.name.endswith(".json"):
                try:
                    # Load relationship from storage
                    relationship_data = json.loads(blob.download_as_string())
                    
                    # Add to in-memory store
                    rel_id = relationship_data["relationship_id"]
                    self.relationship_map[rel_id] = relationship_data
                    
                    relationship_count += 1
                except Exception as e:
                    print(f"Error loading relationship {blob.name}: {e}")
        
        print(f"Loaded {relationship_count} relationships from storage")
        return relationship_count


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Knowledge store management")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--bucket", required=True, help="GCS bucket for knowledge store")
    parser.add_argument("--load", action="store_true", help="Load knowledge from storage")
    parser.add_argument("--query", help="Text query to search for entities")
    
    args = parser.parse_args()
    
    # Initialize knowledge store
    knowledge_store = KnowledgeStore(
        project_id=args.project,
        bucket_name=args.bucket
    )
    
    if args.load:
        entity_count, relationship_count = knowledge_store.load_all_from_storage()
        print(f"Loaded {entity_count} entities and {relationship_count} relationships")
    
    if args.query:
        results = knowledge_store.search_entities(query_text=args.query, top_k=5)
        
        print(f"Search results for '{args.query}':")
        for result in results:
            print(f"  - {result['text']} ({result['type']}): {result['similarity']:.2f}")
            
            # Get relationships
            relationships = knowledge_store.get_entity_relationships(result["entity_id"])
            if relationships:
                print(f"    Relationships: {len(relationships)}")
                for rel in relationships[:3]:  # Show first 3
                    source_id = rel["source_entity_id"]
                    target_id = rel["target_entity_id"]
                    
                    source = knowledge_store.get_entity_by_id(source_id)
                    target = knowledge_store.get_entity_by_id(target_id)
                    
                    print(f"    - {source['text']} -> {rel['relationship_type']} -> {target['text']}")