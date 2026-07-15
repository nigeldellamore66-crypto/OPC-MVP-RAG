# build_index.py
import json
import os
import time
import hashlib
import uuid
from data_ingestion import fetch_events_france
from preprocessing import preprocess_events
from vectorization import split_documents, embeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

COLLECTION_NAME = "puls_events_test_v2"
CHECKPOINT_FILE = "data/qdrant_checkpoint.txt"
region = os.getenv("FILTER_REGION")

# 1. Ingestion / chargement des données nettoyées
if not os.path.exists("data/events_clean.json"):
    if not region:
        events = fetch_events_france() # On récupère TOUT les résultats depuis l'API OpenAgenda
    else:
        events = fetch_events_france(regions=[region])  # On récupère les résultats seulement pour la région définie
    cleaned = preprocess_events(events)
else:
    with open("data/events_clean.json", "r", encoding="utf-8") as f: # On charge les résultats depuis le fichier json déjà présent
        cleaned = json.load(f)

# 2. Découpe en chunks
documents = split_documents(cleaned) # Appelle le découpeur de texte Langchain pour créer des chunks qui seront véctorisés par la suite
print(f"{len(documents)} chunks générés")

# 3. Connexion au serveur Qdrant — gRPC préféré ( connexion persistante)
client = QdrantClient(host="localhost", port=6333, grpc_port=6334, prefer_grpc=True)

collections = [c.name for c in client.get_collections().collections]
if COLLECTION_NAME not in collections: # Créé la collection sur le serveur Qdrant
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
    )
    print(f"Collection '{COLLECTION_NAME}' créée")
else:
    print(f"Collection '{COLLECTION_NAME}' existante, ajout des documents")

# Créé un UID pour chaque chunk
def generer_id_stable(metadata: dict, index_chunk: int) -> str:
    """ID déterministe basé sur le titre + la ville + l'index du chunk.
    Permet une future réindexation incrémentale sans dupliquer :
    réindexer le même événement écrase le point au lieu d'en créer un nouveau."""
    base = f"{metadata.get('title', '')}_{metadata.get('city', '')}_{index_chunk}"
    hash_hex = hashlib.md5(base.encode()).hexdigest()
    return str(uuid.UUID(hash_hex))


# 4. Reprise depuis un éventuel checkpoint si il existe
debut_index = 0 # Commence au début 
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, encoding="utf-8-sig") as f:
        debut_index = int(f.read().strip()) # Commence au checkpoint
    print(f"Reprise depuis le chunk {debut_index}")

# 5. Vectorisation par lots
BATCH_SIZE = 100          
PAUSE = 0.5              
VERIF_TOUS_LES_N_LOTS = 20  # vérification d'intégrité périodique

debut_temps = time.time()

# Boucle du début de l'index jusqu'à la fin des documents à traiter, avec un pas de BATCH_SIZE
for i in range(debut_index, len(documents), BATCH_SIZE):
    batch = documents[i:i + BATCH_SIZE]
    textes = [doc.page_content for doc in batch]

    vecteurs = None
    for tentative in range(5): # Méchanisme de retry pour éviter les erreurs réseau/rate limit
        try:
            vecteurs = embeddings.embed_documents(textes) # vectorise les documents en cours dans le batch
            break
        except Exception as e:
            if tentative < 4:
                print(f"  Erreur ({str(e)[:80]}...) — pause 20s (tentative {tentative+1}/5)")
                time.sleep(20)
            else:
                print(f"  Échec définitif au chunk {i} — checkpoint sauvegardé")
                raise

    # Construit le pointStruct qui est ingéré par Qdrant en ajoutant un UID à chaque document
    points = [
        PointStruct(
            id=generer_id_stable(batch[j].metadata, i + j),
            vector=vecteurs[j],
            payload={**batch[j].metadata, "text": batch[j].page_content}
        )
        for j in range(len(batch))
    ]

    # Écriture avec accusé de réception complet
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
        wait=True
    )

    # Vérification d'intégrité périodique 
    numero_lot = i // BATCH_SIZE
    if numero_lot % VERIF_TOUS_LES_N_LOTS == 0:
        try:
            verif = client.retrieve(collection_name=COLLECTION_NAME, ids=[points[0].id]) # on lit on point pour voir si il est récupérable et bien écrit
            if not verif:
                raise RuntimeError(f"Point {points[0].id} non retrouvé juste après écriture")
        except Exception as e:
            print(f"\n⚠ ALERTE INTÉGRITÉ au lot {i} : {e}")
            print(f"Checkpoint sauvegardé à {i} — corriger avant de relancer")
            raise

    # Ecriture checkpoint après chaque lot réussi
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(i + BATCH_SIZE))

    # Affichage du temps écoulé et estimation temps restant
    fait = min(i + BATCH_SIZE, len(documents))
    ecoule = time.time() - debut_temps
    vitesse = fait / ecoule if ecoule > 0 else 0
    restant_s = (len(documents) - fait) / vitesse if vitesse > 0 else 0
    print(f"{fait}/{len(documents)} chunks indexés "
          f"({ecoule:.0f}s écoulées, ~{restant_s/60:.0f}min restantes)")

    time.sleep(PAUSE)

print(f"\nIndex construit en {(time.time()-debut_temps)/60:.1f} minutes")

if os.path.exists(CHECKPOINT_FILE): # suppression checkpoint
    os.remove(CHECKPOINT_FILE)

client.close() # fermeture connexion grpc