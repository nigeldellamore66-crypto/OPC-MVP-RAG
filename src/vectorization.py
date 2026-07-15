from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_mistralai import MistralAIEmbeddings
from langchain_community.vectorstores import FAISS
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

# Configuration du découpeur de texte Langchain
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=50
)

# Configuration du model d'Embeddings Mistral
embeddings = MistralAIEmbeddings(
    model="mistral-embed",
    api_key=os.getenv("MISTRAL_API_KEY")
)

def split_documents(events):
    documents = []
    for event in events: # Pour chaque évenement de la 
        text = event["text"]
        metadata = dict(event["metadata"]) 
        chunks = text_splitter.create_documents([text], metadatas=[metadata]) # Appelle le découpeur de texte Langchain et retourne un chunk qui sera intégré dans la base Qdrant
        documents.extend(chunks)
    return documents


# NOUVEAU — Qdrant, en parallèle, pour test

QDRANT_PATH = "data/qdrant_db"
COLLECTION_NAME = "puls_events"


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host="qdrant", port=6333)


def build_qdrant_store(documents=None):
    """Crée ou charge la collection."""
    client = get_qdrant_client()

    collections = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME not in collections:
        if documents is None:
            raise ValueError("Aucune collection Qdrant existante et aucun document fourni !")

        print(f"Création de la collection Qdrant avec {len(documents)} documents...")

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
        )

        # Vectorisation par lots pour ne pas saturer l'API Mistral
        BATCH_SIZE = 50
        for i in range(0, len(documents), BATCH_SIZE):
            batch = documents[i:i + BATCH_SIZE]
            textes = [doc.page_content for doc in batch]
            vecteurs = embeddings.embed_documents(textes)

            points = [
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vecteurs[j],
                    payload={**batch[j].metadata, "text": batch[j].page_content}
                )
                for j in range(len(batch))
            ]
            client.upsert(collection_name=COLLECTION_NAME, points=points)
            print(f"  {min(i + BATCH_SIZE, len(documents))}/{len(documents)} indexés")

        print("Collection Qdrant créée.")
    else:
        print(f"Collection Qdrant '{COLLECTION_NAME}' déjà existante, chargement.")

    return client