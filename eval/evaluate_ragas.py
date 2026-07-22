# scripts/evaluer_ragas.py
import csv
import uuid
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, context_recall, answer_correctness
import time
from rag_chain import build_rag_chain
from ragas import RunConfig
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
import os
from qdrant_client import QdrantClient

#  Construit la chaîne 
qdrant_client = QdrantClient(host="localhost", port=6333)
chain = build_rag_chain(qdrant_client, collection_name="puls_events_test_v2")

#  Charge le dataset 
with open("dataset_eval.csv", encoding="utf-8") as f:
    exemples = list(csv.DictReader(f))

#  Exécute le pipeline sur chaque question
donnees = {"question": [], "answer": [], "contexts": [], "ground_truth": []}


for ex in exemples:
    question = ex["question"].strip()

    # Retry si rate limit
    for tentative in range(3):
        try:
            result = chain.invoke(
                {"question": question, "ville_utilisateur": None, "region_utilisateur": "Île-de-France"},
                config={"configurable": {"session_id": str(uuid.uuid4())}}
            )
            break  # succès → on sort de la boucle de retry
        except Exception as e:
            if "429" in str(e) and tentative < 2:
                print(f"  Rate limit — pause 30s...")
                time.sleep(30)
            else:
                raise

    contexts = [doc.get("text", "") for doc in result.get("context", [])]
    if not contexts:
        contexts = ["Aucun contexte récupéré."]

    donnees["question"].append(question)
    donnees["answer"].append(result["answer"])
    donnees["contexts"].append(contexts)
    donnees["ground_truth"].append(ex["ground_truth"].strip())
    print(f"OK - {question[:50]}")

    time.sleep(5)

# ── 4. Évaluation RAGAS ──
dataset = Dataset.from_dict(donnees)

# LLM juge = Mistral (pas OpenAI)
evaluator_llm = LangchainLLMWrapper(ChatMistralAI(
    model="mistral-large-latest",
    api_key=os.getenv("MISTRAL_API_KEY"),
    temperature=0
))
evaluator_emb = LangchainEmbeddingsWrapper(MistralAIEmbeddings(
    model="mistral-embed",
    api_key=os.getenv("MISTRAL_API_KEY")
))

resultats = evaluate(
    dataset,
    metrics=[faithfulness, context_recall, answer_correctness],
    llm=evaluator_llm,           # ← force Mistral
    embeddings=evaluator_emb,    # ← force Mistral
    run_config=RunConfig(max_workers=1)   # ← un seul appel à la fois

)

print("\n" + "="*50)
print(resultats)

df = resultats.to_pandas()
df.to_csv("resultats_ragas_mvp.csv", index=False)

print("\n=== Comparaison POC → MVP ===")
print(f"faithfulness       : 0.41 → {df['faithfulness'].mean():.2f}")
print(f"context_recall     : 0.14 → {df['context_recall'].mean():.2f}")
print(f"answer_correctness : 0.32 → {df['answer_correctness'].mean():.2f}")
print("\nRésultats détaillés dans data/resultats_ragas_mvp.csv")