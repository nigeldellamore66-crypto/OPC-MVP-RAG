# eval/echantillonner.py
import random
import csv
from datetime import datetime
from qdrant_client import QdrantClient

SEUIL = datetime(2026, 6, 1).date()
COLLECTION_NAME = "puls_events_test_v2"  # adapte si besoin

client = QdrantClient(host="localhost", port=6333)

# Récupère un large échantillon de points (scroll = parcours brut, pas de recherche vectorielle)
points, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=500,
    with_payload=True,
    with_vectors=False,
)

print(f"{len(points)} points récupérés depuis Qdrant")

docs_futurs = []
for p in points:
    payload = p.payload
    fin_str = payload.get("date_fin", "") or payload.get("date_debut", "")
    try:
        d_fin = datetime.strptime(fin_str, "%Y-%m-%d").date()
        if d_fin >= SEUIL:
            docs_futurs.append(payload)
    except (ValueError, TypeError):
        continue

print(f"{len(docs_futurs)} événements >= {SEUIL} trouvés")

echantillon = random.sample(docs_futurs, min(25, len(docs_futurs)))

with open("eval/dataset_a_completer.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["question", "ground_truth", "reference_context",
                     "titre", "ville", "date_debut", "date_fin", "categorie"])
    for payload in echantillon:
        writer.writerow([
            "",
            "",
            payload.get("text", ""),
            payload.get("title", ""),
            payload.get("city", ""),
            payload.get("date_debut", ""),
            payload.get("date_fin", ""),
            ""
        ])

print(f"Fichier créé : {len(echantillon)} chunks futurs à compléter")