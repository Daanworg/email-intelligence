"""
Entity extraction module for the Email Intelligence System.
Extracts entities such as people, projects, and key terms from processed documents.
"""

import re
import json
import uuid
from typing import List, Dict, Any, Set, Tuple

from google.cloud import storage, bigquery
import vertexai
from vertexai.preview.language_models import TextEmbeddingModel
from vertexai.preview.generative_models import GenerativeModel


class EntityExtractor:
    """Extracts entities from processed documents."""
    
    def __init__(
        self,
        project_id: str,
        output_bucket: str,
        entity_types: List[str] = None,
        embedding_model_name: str = "text-embedding-004",
        llm_model_name: str = "gemini-pro"
    ):
        """Initialize the entity extractor.
        
        Args:
            project_id: Google Cloud project ID
            output_bucket: GCS bucket to store results
            entity_types: List of entity types to extract (defaults to ["PERSON", "PROJECT", "TERM"])
            embedding_model_name: Name of the embedding model to use
            llm_model_name: Name of the generative model to use
        """
        self.project_id = project_id
        self.output_bucket = output_bucket
        self.entity_types = entity_types or ["PERSON", "PROJECT", "TERM"]
        self.embedding_model_name = embedding_model_name
        self.llm_model_name = llm_model_name
        
        # Initialize clients
        self.storage_client = storage.Client(project=project_id)
        self.bq_client = bigquery.Client(project=project_id)
        
        # Initialize AI models
        self.embedding_model = TextEmbeddingModel.from_pretrained(embedding_model_name)
        self.llm_model = GenerativeModel(llm_model_name)
    
    def extract_entities_from_document(self, document_content: str, document_id: str) -> List[Dict[str, Any]]:
        """Extract entities from a document.
        
        Args:
            document_content: Text content of the document
            document_id: Identifier for the document
            
        Returns:
            List of entity dictionaries
        """
        print(f"Extracting entities from document: {document_id}")
        
        # Extract entities using multiple approaches and combine results
        ai_entities = self._extract_entities_with_ai(document_content)
        pattern_entities = self._extract_entities_with_patterns(document_content)
        
        # Combine entities and remove duplicates
        combined_entities = self._combine_entity_results(ai_entities, pattern_entities)
        
        # Enrich entities with additional information
        enriched_entities = self._enrich_entities(combined_entities, document_content, document_id)
        
        return enriched_entities
    
    def _extract_entities_with_ai(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities using AI models.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            List of entity dictionaries
        """
        # Maximum text length to send to the model (in chunks)
        max_chunk_length = 16000
        
        entities = []
        
        # Split long text into chunks for processing
        text_chunks = [text[i:i+max_chunk_length] for i in range(0, len(text), max_chunk_length)]
        
        for chunk_idx, chunk in enumerate(text_chunks):
            print(f"Processing entity extraction for chunk {chunk_idx+1}/{len(text_chunks)}")
            
            # Use a prompt to identify entity types of interest
            prompt = f"""
            Extract the entities from the following text. Only extract PERSON (individual names), 
            PROJECT (project names, initiatives, products), and TERM (important technical or business terms).
            
            Format your response as a JSON array, where each item is an object with "text", "type", and "relevance" 
            (a score from 0.0 to 1.0 indicating confidence and importance).
            
            Example:
            [
                {{"text": "John Smith", "type": "PERSON", "relevance": 0.85}},
                {{"text": "Cloud Migration", "type": "PROJECT", "relevance": 0.95}},
                {{"text": "Kubernetes", "type": "TERM", "relevance": 0.78}}
            ]
            
            Text:
            {chunk}
            
            JSON Result:
            """
            
            try:
                response = self.llm_model.generate_content(prompt)
                
                # Parse JSON response
                try:
                    # Clean up any markdown formatting in the response
                    clean_response = re.sub(r'```(json)?|```', '', response.text.strip())
                    result = json.loads(clean_response)
                    
                    if isinstance(result, list):
                        # Add chunk info to entities
                        for entity in result:
                            entity["chunk_index"] = chunk_idx
                        
                        entities.extend(result)
                    
                except json.JSONDecodeError as e:
                    print(f"Error parsing entity extraction response: {e}")
                    print(f"Response was: {response.text[:500]}")
            
            except Exception as e:
                print(f"Error in AI entity extraction: {e}")
        
        return entities
    
    def _extract_entities_with_patterns(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities using regex patterns and heuristics.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            List of entity dictionaries
        """
        entities = []
        
        # Pattern for email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        
        for email in emails:
            # Extract potential person name from email (before @)
            name_part = email.split('@')[0].replace('.', ' ').replace('_', ' ').replace('-', ' ')
            # Only use if it looks like a name (at least 2 parts, each capitalized)
            name_parts = name_part.split()
            
            if len(name_parts) >= 2 and all(part[0].isupper() for part in name_parts if part):
                formatted_name = ' '.join(name_parts).title()
                entities.append({
                    "text": formatted_name,
                    "type": "PERSON",
                    "relevance": 0.7,
                    "metadata": {"email": email}
                })
        
        # Pattern for project codes/identifiers (e.g., PRJ-123, PROJECT-ABC)
        project_code_pattern = r'\b(?:PRJ|PROJECT|PROJ)-[A-Z0-9]{2,6}\b'
        project_codes = re.findall(project_code_pattern, text, re.IGNORECASE)
        
        for code in project_codes:
            entities.append({
                "text": code.upper(),
                "type": "PROJECT",
                "relevance": 0.8,
                "metadata": {"is_code": True}
            })
        
        # Identify technical terms based on common patterns
        term_patterns = [
            r'\b[A-Z][a-z]*[A-Z][a-z]*\b',  # CamelCase terms (likely technical)
            r'\b[A-Z]{2,}\b',               # Acronyms
            r'\b\w+\s+API\b',               # API references
            r'\b\w+\s+service\b',           # Service references
            r'\b\w+\s+platform\b'           # Platform references
        ]
        
        for pattern in term_patterns:
            terms = re.findall(pattern, text)
            for term in terms:
                if len(term) > 3:  # Skip very short terms
                    entities.append({
                        "text": term,
                        "type": "TERM",
                        "relevance": 0.6,
                        "metadata": {"pattern_matched": pattern}
                    })
        
        return entities
    
    def _combine_entity_results(self, ai_entities: List[Dict], pattern_entities: List[Dict]) -> List[Dict]:
        """Combine and deduplicate entity results.
        
        Args:
            ai_entities: Entities extracted with AI
            pattern_entities: Entities extracted with patterns
            
        Returns:
            Combined and deduplicated entity list
        """
        # Use a dictionary for deduplication, with text+type as key
        entity_map = {}
        
        # Process AI entities first (typically higher quality)
        for entity in ai_entities:
            key = (entity["text"].lower(), entity["type"])
            
            if key not in entity_map or entity.get("relevance", 0) > entity_map[key].get("relevance", 0):
                entity_map[key] = entity
        
        # Add pattern entities if not already present or if they have higher relevance
        for entity in pattern_entities:
            key = (entity["text"].lower(), entity["type"])
            
            if key not in entity_map or entity.get("relevance", 0) > entity_map[key].get("relevance", 0):
                entity_map[key] = entity
        
        # Convert back to list
        combined = list(entity_map.values())
        
        # Sort by relevance (descending)
        combined.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        
        return combined
    
    def _enrich_entities(self, entities: List[Dict], document_text: str, document_id: str) -> List[Dict]:
        """Enrich entities with additional information.
        
        Args:
            entities: List of extracted entities
            document_text: Full text of the document
            document_id: Document identifier
            
        Returns:
            List of enriched entity dictionaries
        """
        enriched_entities = []
        
        for entity in entities:
            # Generate a stable entity ID based on text and type
            entity_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{entity['text'].lower()}-{entity['type']}"))
            
            # Generate embedding for the entity
            entity_text = entity["text"]
            entity_embedding = self.embedding_model.get_embeddings([entity_text])[0].values
            
            # Find contexts where this entity appears
            contexts = self._find_entity_contexts(entity_text, document_text)
            
            # Create enriched entity
            enriched_entity = {
                "entity_id": entity_id,
                "text": entity["text"],
                "type": entity["type"],
                "relevance": entity.get("relevance", 0.5),
                "embedding": entity_embedding,
                "source_documents": [document_id],
                "contexts": contexts[:5],  # Limit to top 5 contexts
                "metadata": entity.get("metadata", {})
            }
            
            enriched_entities.append(enriched_entity)
        
        return enriched_entities
    
    def _find_entity_contexts(self, entity_text: str, document_text: str, context_window: int = 100) -> List[str]:
        """Find contexts where an entity appears in the document.
        
        Args:
            entity_text: Entity text to find
            document_text: Document text to search in
            context_window: Number of characters before and after to include
            
        Returns:
            List of context snippets
        """
        contexts = []
        
        # Escape special regex characters in entity text
        escaped_entity = re.escape(entity_text)
        
        # Find all occurrences
        for match in re.finditer(escaped_entity, document_text, re.IGNORECASE):
            start = max(0, match.start() - context_window)
            end = min(len(document_text), match.end() + context_window)
            
            # Extract context
            context = document_text[start:end].strip()
            
            # Add ellipsis if truncated
            if start > 0:
                context = "..." + context
            if end < len(document_text):
                context = context + "..."
            
            contexts.append(context)
        
        return contexts
    
    def extract_relationships(self, entities: List[Dict], document_text: str) -> List[Dict]:
        """Extract relationships between entities.
        
        Args:
            entities: List of extracted entities
            document_text: Document text
            
        Returns:
            List of relationship dictionaries
        """
        relationships = []
        
        # Only process if we have multiple entities
        if len(entities) < 2:
            return relationships
        
        # Identify potential entity pairs
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                # Skip if entities are the same type
                if entity1["type"] == entity2["type"]:
                    continue
                
                # Check if entities appear near each other in text
                proximity_score = self._check_entity_proximity(entity1["text"], entity2["text"], document_text)
                
                if proximity_score > 0:
                    # Generate a relationship type based on entity types
                    relationship_type = self._infer_relationship_type(entity1, entity2)
                    
                    # Create relationship entry
                    relationship = {
                        "source_entity_id": entity1["entity_id"],
                        "target_entity_id": entity2["entity_id"],
                        "source_type": entity1["type"],
                        "target_type": entity2["type"],
                        "relationship_type": relationship_type,
                        "confidence": proximity_score,
                        "relationship_id": str(uuid.uuid4())
                    }
                    
                    relationships.append(relationship)
        
        return relationships
    
    def _check_entity_proximity(self, entity1_text: str, entity2_text: str, document_text: str, window_size: int = 200) -> float:
        """Check if two entities appear close to each other in text.
        
        Args:
            entity1_text: First entity text
            entity2_text: Second entity text
            document_text: Document text to search in
            window_size: Character window to search in
            
        Returns:
            Proximity score between 0 and 1 (0 means not in proximity)
        """
        # Escape special regex characters
        escaped_entity1 = re.escape(entity1_text)
        escaped_entity2 = re.escape(entity2_text)
        
        # Find all occurrences of both entities
        entity1_positions = [(m.start(), m.end()) for m in re.finditer(escaped_entity1, document_text, re.IGNORECASE)]
        entity2_positions = [(m.start(), m.end()) for m in re.finditer(escaped_entity2, document_text, re.IGNORECASE)]
        
        if not entity1_positions or not entity2_positions:
            return 0
        
        # Check if any occurrences are within the window
        min_distance = float('inf')
        for start1, end1 in entity1_positions:
            for start2, end2 in entity2_positions:
                # Calculate the distance between the two entities
                if start2 >= end1:
                    distance = start2 - end1  # entity2 is after entity1
                elif start1 >= end2:
                    distance = start1 - end2  # entity1 is after entity2
                else:
                    distance = 0  # Entities overlap
                
                min_distance = min(min_distance, distance)
        
        # Convert distance to proximity score
        if min_distance == float('inf'):
            return 0
        elif min_distance <= window_size:
            # Linearly decrease score as distance increases
            return max(0, 1 - (min_distance / window_size))
        else:
            return 0
    
    def _infer_relationship_type(self, entity1: Dict, entity2: Dict) -> str:
        """Infer relationship type based on entity types.
        
        Args:
            entity1: First entity dictionary
            entity2: Second entity dictionary
            
        Returns:
            Relationship type as string
        """
        # Order entities so source is preferred as PERSON, then PROJECT, then TERM
        source, target = entity1, entity2
        if _entity_type_priority(entity2["type"]) < _entity_type_priority(entity1["type"]):
            source, target = entity2, entity1
        
        # Map relationships based on entity types
        relationship_map = {
            ("PERSON", "PROJECT"): "WORKS_ON",
            ("PERSON", "TERM"): "EXPERTISE_IN",
            ("PROJECT", "TERM"): "USES"
        }
        
        return relationship_map.get((source["type"], target["type"]), "RELATED_TO")


def _entity_type_priority(entity_type: str) -> int:
    """Helper to determine entity type priority.
    
    Args:
        entity_type: Entity type string
        
    Returns:
        Priority value (lower is higher priority)
    """
    priorities = {"PERSON": 0, "PROJECT": 1, "TERM": 2}
    return priorities.get(entity_type, 99)


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extract entities from a document")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--bucket", required=True, help="GCS bucket for processed documents")
    parser.add_argument("--document", required=True, help="Document GCS path")
    
    args = parser.parse_args()
    
    # Initialize GCS client
    storage_client = storage.Client(project=args.project)
    
    # Read document content
    bucket_name, blob_path = args.document.replace("gs://", "").split("/", 1)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    document_content = blob.download_as_text()
    
    # Initialize entity extractor
    extractor = EntityExtractor(
        project_id=args.project,
        output_bucket=args.bucket
    )
    
    # Extract entities
    entities = extractor.extract_entities_from_document(document_content, args.document)
    
    # Extract relationships
    relationships = extractor.extract_relationships(entities, document_content)
    
    # Print results
    print(f"Extracted {len(entities)} entities:")
    for entity in entities[:5]:  # Print first 5
        print(f"  - {entity['text']} ({entity['type']}): {entity['relevance']:.2f}")
    
    print(f"\nExtracted {len(relationships)} relationships:")
    for rel in relationships[:5]:  # Print first 5
        print(f"  - {rel['source_type']} -> {rel['relationship_type']} -> {rel['target_type']} ({rel['confidence']:.2f})")