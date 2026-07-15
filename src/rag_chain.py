from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableParallel
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
from dotenv import load_dotenv
import os
import re
from datetime import datetime, timedelta, date
from geo import normaliser, extraire_ville, extraire_region
from vectorization import embeddings

# 1. CHARGEMENT DU PROMPT SYSTÈME

load_dotenv()

# Date du jour et période de couverture
today_dt = datetime.now()
couverture_debut = (today_dt - timedelta(days=365)).strftime("%d/%m/%Y")

prompt_env = os.getenv("PROMPT_SYSTEM")
# Garde fou pour prompt absent
if not prompt_env:
    raise ValueError(
        "PROMPT_SYSTEM introuvable — vérifie que le fichier .env existe "
        "à la racine du projet et contient la variable PROMPT_SYSTEM"
    )
# Injection des dates dans le prompt
template = (
    prompt_env
    .replace("{today}", today_dt.strftime("%d/%m/%Y"))
    .replace("{couverture_debut}", couverture_debut)
)

# 2. MÉMOIRE CONVERSATIONNELLE (sessions)

session_store = {}

# Récupère l'historique de conversation de la session
def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in session_store:
        session_store[session_id] = ChatMessageHistory()
    return session_store[session_id]

# Formate l'historique selon le nombre de messages (6 max)
def format_history(messages) -> str:
    if not messages:
        return "Aucun échange précédent."
    messages = messages[-6:]
    lines = []
    for msg in messages:
        role = "Utilisateur" if msg.type == "human" else "Assistant"
        lines.append(f"{role} : {msg.content}")
    return "\n".join(lines)

# 3. DÉTECTION TEMPORELLE DANS LA QUESTION

MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12
}

MOTS_FUTUR = ["à venir", "a venir", "prochain", "auront lieu", "futur",
              "bientôt", "bientot", "prévu", "prevu", "programmé", "programme"]
MOTS_PASSE = ["passé", "passe", "dernier", "derniere", "ont eu lieu",
              "précédent", "precedent", "a eu lieu"]


def extraire_criteres_temporels(question: str) -> dict:
    q = question.lower()
    maintenant = datetime.now()

    mois = next((num for nom, num in MOIS_FR.items() if nom in q), None) # détecte le mois mentionné dans la question
    annee_match = re.search(r"20\d{2}", question) # détecte l'année mentionnée dans la question
    annee = int(annee_match.group()) if annee_match else None

    # utilise le mois courant de l'année courante si on utilise "ce mois" dans la question
    if "ce mois" in q:
        mois = maintenant.month
        annee = maintenant.year

    # si on mentionne que le mois, on détecte l'année courante
    if mois and not annee:
        annee = maintenant.year

    # détecte l'intention de passé ou futur dans la question à l'aide des dictionnaires de mots
    intention = None
    if any(m in q for m in MOTS_FUTUR):
        intention = "futur"
    elif any(m in q for m in MOTS_PASSE):
        intention = "passe"

    return {"mois": mois, "annee": annee, "intention": intention}

# 4. FILTRE QDRANT NATIF 

def construire_filtre_qdrant(criteres: dict, ville: str, region: str) -> Filter:
    """Traduit les critères détectés en filtre natif Qdrant.
    Utilise des timestamps numériques (date_debut_ts/date_fin_ts) car
    Qdrant Range exige des valeurs numériques, pas des chaînes de date."""
    conditions = []
    aujourd_hui_ts = int(datetime.now().timestamp())

    if criteres["intention"] == "futur": # Si intention futur: date supérieure à aujourd'hui
        conditions.append(FieldCondition(key="date_fin_ts", range=Range(gte=aujourd_hui_ts)))
    elif criteres["intention"] == "passe": # Si intention passé: date inférieure à aujourd'hui
        conditions.append(FieldCondition(key="date_debut_ts", range=Range(lt=aujourd_hui_ts)))

    # Filtrage temporel avec mois et anéée
    if criteres["mois"] and criteres["annee"]:
        m, a = criteres["mois"], criteres["annee"]
        debut_ts = int(datetime(a, m, 1).timestamp())
        fin_ts = int((datetime(a, m + 1, 1) if m < 12 else datetime(a, 12, 31)).timestamp())
        conditions.append(FieldCondition(key="date_fin_ts", range=Range(gte=debut_ts)))
        conditions.append(FieldCondition(key="date_debut_ts", range=Range(lte=fin_ts)))
    elif criteres["annee"]: # Filtrage temporel si seulement l'année
        conditions.append(FieldCondition(key="date_debut_ts", range=Range(
            gte=int(datetime(criteres["annee"], 1, 1).timestamp()),
            lte=int(datetime(criteres["annee"], 12, 31).timestamp())
        )))

    # si une ville est renseignée on l'inclut au contexte, sinon la région
    if ville:
        conditions.append(FieldCondition(key="city", match=MatchValue(value=normaliser(ville))))
    elif region:
        conditions.append(FieldCondition(key="region", match=MatchValue(value=region)))

    return Filter(must=conditions) if conditions else None


def construire_index_villes_qdrant(client, collection_name: str, limite_totale: int = 5000) -> set:
    """Parcourt la base Qdrant pour lister toutes les villes distinctes qu'elle contient, afin d'alimenter extraire_ville(question, villes_connues) 
    — la fonction qui détecte si une question mentionne une ville connue"""
    villes = set()
    offset = None
    LOT = 200

    try:
        while len(villes) < limite_totale: # Dans la limite définie, scroll a travers toutes les villes pour trouver les occurences recherchées
            points, offset = client.scroll(
                collection_name=collection_name,
                limit=LOT,
                offset=offset,
                with_payload=["city"],
                with_vectors=False,
            )
            if not points:
                break
            for p in points:
                ville = p.payload.get("city", "")
                if ville:
                    villes.add(ville)
            if offset is None:
                break
    except Exception as e: # Permet d'éviter de crasher l'application entière en cas d'index corrompu
        print(f"⚠ Impossible de construire l'index des villes ({e}) — "
              f"détection de ville limitée au profil utilisateur")

    return villes

# 5. CONSTRUCTION DE LA CHAÎNE RAG (Qdrant)

def build_rag_chain(qdrant_client, collection_name: str = "puls_events"):
    """ Fonction appelée une seule fois au démarrage de l'app (dans app.py), elle retourne la chaîne complète prête à traiter des questions.
"""
    llm = ChatMistralAI( # Configuration de l'object LangChain qui sait parler à l'API Mistral
        model=os.getenv("MISTRAL_MODEL"),
        api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0,
        max_tokens=1500,
    )

    prompt = PromptTemplate( # Prend le texte brut du prompt système ( avec date etc...) et indique qu'il faut encore y injecter le contexte, la question et l'historique
        template=template,
        input_variables=["context", "question", "chat_history"]
    )

    chain = ( # Assemblage de la chaîne LangChain
        prompt
        | llm
        | StrOutputParser()
    )

    # Index des villes connues, construit une fois au démarrage
    villes_connues = construire_index_villes_qdrant(qdrant_client, collection_name)

    def retriever_intelligent(inputs: dict) -> list:
        question = inputs["question"] # inputs: dictionnaire fourni par LangChain contenant tout les éléments de la question

        # ── 1. Critères temporels: cherche mois, année , intention dans la question
        criteres = extraire_criteres_temporels(question)

        if not criteres["mois"] and not criteres["annee"] and not criteres["intention"]: # Si aucun critère fourni dans la question, on regarde dans l'historique
            for msg in reversed(inputs.get("chat_history", [])):
                if msg.type == "human":
                    criteres_prec = extraire_criteres_temporels(msg.content)
                    if criteres_prec["mois"] or criteres_prec["annee"] or criteres_prec["intention"]:
                        criteres = criteres_prec
                        break
        # Le critère par défaut est un évenement dans le futur
        if not criteres["mois"] and not criteres["annee"] and not criteres["intention"]:
            criteres["intention"] = "futur"

        # 2. Critères géographiques ──
        ville = extraire_ville(question, villes_connues) or inputs.get("ville_utilisateur")
        region = extraire_region(question) or inputs.get("region_utilisateur")

        print(f"DEBUG — ville retenue: {ville!r} | region retenue: {region!r}")  # ← ajoute cette ligne temporairement
        
        if extraire_region(question) and not extraire_ville(question, villes_connues): # Si la question mentionne une région mais pas de ville on éfface la région
            ville = None

        # 3. Recherche Qdrant avec filtre natif
        vecteur = embeddings.embed_query(question) # vectorisation de la question par Mistral

        filtre = construire_filtre_qdrant(criteres, ville, region) # Traduit tout les critère en filtre Qdrant
        resultats = qdrant_client.query_points( # Lance la recherche sur la base Qdrant ( élminie d'abord tout les éléments qui ne correspondent pas aux filtres, puis renvoie les 12 meilleurs resultats)
            collection_name=collection_name, 
            query=vecteur,
            query_filter=filtre,
            limit=12
        ).points

        # 4. Repli si la ville n'est pas trouvé on prends la région comme critère géographique
        if ville and not resultats and region:
            filtre_repli = construire_filtre_qdrant(criteres, None, region)
            resultats = qdrant_client.query_points(
                collection_name=collection_name,
                query=vecteur,
                query_filter=filtre_repli,
                limit=12
            ).points

        return [r.payload for r in resultats]

    # Assemblage LCEL 
    chain_with_source = RunnableParallel( # Construit un dictionnaire de résultats en éxecutant en parallèle plusieurs opérations sur input ( context, question, history)
        context=retriever_intelligent,
        question=lambda x: x["question"],
        chat_history=lambda x: format_history(x.get("chat_history", [])),
    ).assign(answer=chain)

    chain_with_memory = RunnableWithMessageHistory( # Chaîne complète: recherche + mémoire
        chain_with_source,
        get_session_history,
        input_messages_key="question",
        history_messages_key="chat_history",
        output_messages_key="answer",
    )

    return chain_with_memory