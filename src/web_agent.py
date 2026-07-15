from smolagents import CodeAgent, Tool, LiteLLMModel
from tavily import TavilyClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

class TavilySearchTool(Tool):
    name = "web_search"
    description = "Recherche des événements culturels actuels sur le web."
    inputs = {
        "query": {"type": "string", "description": "Requête courte, 3-5 mots"}
    }
    output_type = "string"

    def forward(self, query: str) -> str:
        r = tavily_client.search(query=query, max_results=5, search_depth="basic")
        if not r.get("results"):
            return "Aucun résultat."
        return "\n\n".join(
            f"- {x['title']}\n  {x['content'][:300]}\n  {x['url']}"
            for x in r["results"]
        )

model = LiteLLMModel(
    model_id="mistral/mistral-medium-latest",
    api_key=os.getenv("MISTRAL_API_KEY"),
    temperature=0,
)

agent = CodeAgent(
    tools=[TavilySearchTool()],
    model=model,
    max_steps=2,
    verbosity_level=0,
)

def rechercher_evenements_web(question: str, ville: str = None,
                               region: str = None) -> str | None:
    aujourd_hui = datetime.now()
    zone = ville or region or "France"

    consigne = f"""Nous sommes en {aujourd_hui.strftime('%B %Y')}. Recherche : {question}
Zone : {zone}, France. Événements à venir uniquement.

RÈGLES ABSOLUES :
- Utilise UNIQUEMENT les résultats de l'outil web_search
- INTERDICTION d'inventer événements, dates ou artistes
- Si aucun résultat fiable : réponds exactement ECHEC_RECHERCHE
- Jamais de "sites où chercher" ni d'exemples "typiques"
- Maximum 5 événements : nom, date, lieu, description courte, en français"""

    try:
        texte = str(agent.run(consigne))
    except Exception:
        return None

    # Garde-fou anti-improvisation
    marqueurs = ["ECHEC_RECHERCHE", "typiques", "récurrents",
                 "consultez", "vous pourriez", "où chercher"]
    if any(m in texte.lower() for m in [x.lower() for x in marqueurs]):
        return None
    return texte