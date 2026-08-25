"""
RAG-based Prescription Verifier.
Extracts drugs from prescription text, fetches knowledge from ChromaDB,
and uses Gemini to assess safety, interactions, and UAE MOH compliance.
"""
import os
import json
import re
from typing import Dict, Any, List

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from langchain_google_genai import ChatGoogleGenerativeAI
from src.knowledge.drug_database import DRUG_NAME_INDEX

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./data/chroma_db")

# Cached singletons — client construction is setup cost, not per-request work.
# Each verify_prescription() makes two LLM calls; recreating clients per call
# added avoidable latency to every verification.
_cached_llm = None
_cached_collection = None


def _get_llm():
    """Reuse one Gemini client across verifications."""
    global _cached_llm
    if _cached_llm is None:
        _cached_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.1)
    return _cached_llm


def extract_drugs_from_text(prescription_text: str) -> List[str]:
    """Use LLM to extract medication names from raw prescription text."""
    llm = _get_llm()
    prompt = f"""Extract all medication names from this prescription text.
Return ONLY a comma-separated list of drug names. No other text.
If no drugs are found, return "NONE".

Prescription:
{prescription_text}"""
    
    response = llm.invoke(prompt).content.strip()
    if response == "NONE" or not response:
        return []
    
    drugs = [d.strip() for d in response.split(",")]
    return drugs


def retrieve_drug_knowledge(drugs: List[str], patient_info: str = "") -> str:
    """Retrieve relevant drug safety info and interactions from ChromaDB."""
    if not drugs:
        return "No known drugs identified."

    try:
        global _cached_collection
        if _cached_collection is None:
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            _cached_collection = client.get_collection(
                name="drug_knowledge",
                embedding_function=DefaultEmbeddingFunction()
            )
        collection = _cached_collection
    except Exception as e:
        print(f"Warning: ChromaDB not found or error. Run build_drug_database.py. Error: {e}")
        return "Knowledge base unavailable."

    knowledge_chunks = []
    
    # 1. Fetch exact matches from local index; explicitly mark drugs that are
    # NOT in the index so the model treats them as unverified rather than
    # silently trusting an LLM-hallucinated drug name.
    unverified_drugs = []
    for drug in drugs:
        drug_lower = drug.lower()
        if drug_lower in DRUG_NAME_INDEX:
            db_drug = DRUG_NAME_INDEX[drug_lower]
            knowledge_chunks.append(f"EXACT MATCH [{db_drug['name']}]: {db_drug['knowledge_text']}")
        else:
            unverified_drugs.append(drug)
    if unverified_drugs:
        knowledge_chunks.append(
            f"WARNING: The following identified drugs were NOT found in the local "
            f"drug index: {', '.join(unverified_drugs)}. Treat any analysis of them "
            f"as UNVERIFIED and recommend pharmacist confirmation."
        )

    # 2. Use RAG for interactions and general safety (especially involving patient context)
    query_texts = drugs.copy()
    if len(drugs) > 1:
        query_texts.append(" interaction ".join(drugs))
    if patient_info:
        query_texts.append(f"Contraindications for: {patient_info}")

    results = collection.query(
        query_texts=query_texts,
        n_results=3
    )

    for doc_list in results['documents']:
        for doc in doc_list:
            if doc not in knowledge_chunks:
                knowledge_chunks.append(doc)

    return "\n".join(knowledge_chunks)


def verify_prescription(prescription_text: str, patient_info: str) -> Dict[str, Any]:
    """
    Main verification pipeline:
    1. Extract drugs
    2. Retrieve knowledge
    3. Analyze safety (Interactions, Dosages, Contraindications)
    4. Format output
    """
    drugs = extract_drugs_from_text(prescription_text)
    knowledge = retrieve_drug_knowledge(drugs, patient_info)
    
    llm = _get_llm()
    
    prompt = f"""You are an expert Clinical Pharmacist in the UAE.
Review the following prescription and patient information against the provided Drug Knowledge Base.

DRUGS IDENTIFIED: {', '.join(drugs) if drugs else 'None'}

PATIENT INFO:
{patient_info}

PRESCRIPTION DETAILS:
{prescription_text}

DRUG KNOWLEDGE BASE (Retrieved context):
{knowledge}

Analyze for:
1. Drug-Drug Interactions (critical)
2. Contraindications (allergies, pregnancy, age, diseases)
3. Dosage appropriateness (if doses are provided in the prescription)
4. UAE MOH Regulations (if mentioned in knowledge base)

Return ONLY valid JSON in this exact format:
{{
    "risk_level": "LOW|MEDIUM|HIGH",
    "is_safe_to_dispense": true/false,
    "identified_drugs": ["drug1", "drug2"],
    "interactions_found": ["interaction details or 'None'"],
    "contraindications_found": ["contraindication details or 'None'"],
    "dosage_warnings": ["dosage warnings or 'None'"],
    "pharmacist_recommendation": "Clear instruction on what the pharmacist should do (e.g., 'Dispense as written', 'Call doctor to change X to Y', 'Counsel patient on Z')"
}}"""

    response = llm.invoke(prompt).content.strip()
    
    # Robust JSON extraction — extraction regex handles markdown fences and
    # surrounding prose. On failure we FAIL SAFE: unparsed output means the
    # safety check did not complete, so the prescription must be reviewed by
    # a human rather than assumed safe.
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
        else:
            result = json.loads(response)
    except Exception as e:
        result = {
            "risk_level": "HIGH",
            "is_safe_to_dispense": False,
            "identified_drugs": drugs,
            "interactions_found": ["Error parsing AI response"],
            "contraindications_found": [],
            "dosage_warnings": [],
            "pharmacist_recommendation": "SYSTEM ERROR: Review manually. Failed to parse AI safety check."
        }

    return result
