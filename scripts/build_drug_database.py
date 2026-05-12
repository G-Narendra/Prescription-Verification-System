"""
Build ChromaDB vector store from the drug knowledge base.
Run once: python scripts/build_drug_database.py
"""
import os
import sys
from pathlib import Path

base_dir = Path(__file__).parent.parent
sys.path.append(str(base_dir))

from dotenv import load_dotenv
load_dotenv(base_dir / ".env")

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from src.knowledge.drug_database import DRUG_DATABASE

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")


def build_database():
    print("Building ChromaDB drug knowledge base...")
    Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Drop and recreate for fresh build
    try:
        client.delete_collection("drug_knowledge")
    except Exception:
        pass

    collection = client.create_collection(
        name="drug_knowledge",
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"description": "UAE Prescription Drug Knowledge Base"},
    )

    documents, metadatas, ids = [], [], []
    for drug in DRUG_DATABASE:
        # Main knowledge document
        doc_text = drug["knowledge_text"]
        meta = {
            "drug_id": drug["id"],
            "name": drug["name"],
            "category": drug["category"],
            "pregnancy_category": drug["pregnancy_category"],
            "max_dose_adult": str(drug.get("max_daily_dose", {}).get("adult", "")),
            "contraindications": ", ".join(drug.get("contraindications", [])),
            "uae_notes": drug.get("uae_moh_notes", ""),
        }
        documents.append(doc_text)
        metadatas.append(meta)
        ids.append(f"drug_{drug['id']}")

        # Add individual interaction documents for better RAG recall
        for ix in drug.get("interactions", []):
            ix_text = (
                f"Drug interaction: {drug['name']} + {ix['drug']} — "
                f"Severity: {ix['severity'].upper()}. Effect: {ix['effect']}"
            )
            documents.append(ix_text)
            metadatas.append({
                "drug_id": drug["id"],
                "name": drug["name"],
                "interaction_drug": ix["drug"],
                "severity": ix["severity"],
                "type": "interaction",
                "category": drug["category"],
                "pregnancy_category": drug["pregnancy_category"],
                "max_dose_adult": str(drug.get("max_daily_dose", {}).get("adult", "")),
                "contraindications": ", ".join(drug.get("contraindications", [])),
                "uae_notes": drug.get("uae_moh_notes", ""),
            })
            ids.append(f"ix_{drug['id']}_{ix['drug'].lower().replace(' ', '_')}")

    collection.add(documents=documents, metadatas=metadatas, ids=ids)
    print(f"[OK] Added {len(documents)} documents ({len(DRUG_DATABASE)} drugs + interactions)")
    print(f"[OK] ChromaDB saved to: {CHROMA_PATH}")


if __name__ == "__main__":
    build_database()
