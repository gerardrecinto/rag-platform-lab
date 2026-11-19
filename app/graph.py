"""Small GraphRAG layer: chunks and the clinical terms they mention, in Neo4j.

The vocabulary is a short synthetic list. A real system would use an entity extractor.
"""
import re

from neo4j import GraphDatabase

from . import config

VOCAB = {"anxiety", "depression", "insomnia", "panic", "sertraline", "cbt", "therapy", "sleep", "mindfulness", "burnout"}
WORD = re.compile(r"[a-z]+")
_driver = None


def entities(text):
    return sorted({w for w in WORD.findall(text.lower()) if w in VOCAB})


def driver():
    global _driver
    if _driver is None and config.NEO4J_URI:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=config.NEO4J_AUTH)
    return _driver


def add_chunk(chunk_id, text):
    d = driver()
    if d is None:
        return
    with d.session() as s:
        s.run("MERGE (c:Chunk {id: $id})", id=chunk_id)
        for e in entities(text):
            s.run("MATCH (c:Chunk {id: $id}) MERGE (t:Term {name: $e}) MERGE (c)-[:MENTIONS]->(t)", id=chunk_id, e=e)


def related_chunks(chunk_ids, limit=3):
    """Chunks that share a term with the given chunks, most shared terms first."""
    d = driver()
    if d is None or not chunk_ids:
        return []
    with d.session() as s:
        rows = s.run(
            "MATCH (c:Chunk)-[:MENTIONS]->(t:Term)<-[:MENTIONS]-(o:Chunk) "
            "WHERE c.id IN $ids AND NOT o.id IN $ids "
            "RETURN o.id AS id, count(DISTINCT t) AS shared ORDER BY shared DESC, id LIMIT $limit",
            ids=list(chunk_ids), limit=limit)
        return [r["id"] for r in rows]
