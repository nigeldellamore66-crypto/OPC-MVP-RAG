# Puls-Events — Assistant RAG pour événements culturels - MVP

Assistant conversationnel permettant de découvrir des événements culturels en Île-de-France (extension France entière en cours) via une interface en langage naturel, construit avec une architecture RAG (Retrieval Augmented Generation).

> Projet OpenClassrooms — transformation d'un POC validé en MVP scalable.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Stack technique](#stack-technique)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Structure du projet](#structure-du-projet)
- [Évaluation](#évaluation)
- [Limites connues](#limites-connues--roadmap)

---

## Fonctionnalités

- **Recherche en langage naturel** — "Quels concerts à Paris ce mois-ci ?"
- **Mémoire conversationnelle** — questions de suivi sans répéter le contexte ("et à Versailles ?")
- **Contexte géographique** — détection automatique (IP) ou manuelle de la localisation, avec repli intelligent ville → région
- **Filtrage temporel intelligent** — priorité aux événements à venir par défaut, détection explicite du passé
- **Recherche web de secours** — bascule automatique sur le web (agent [smolagents](https://github.com/huggingface/smolagents) + Tavily) si la base locale ne trouve rien
- **Monitoring** — dashboard temps réel (taux d'échec, latence, feedback utilisateur)

## Architecture

```
Utilisateur (Streamlit)
      │
      ▼
Détection localisation (IP + sidebar)
      │
      ▼
Retriever intelligent ──► Détection critères (temporel, géo)
      │                        │
      │                        ▼
      │                  Filtre natif Qdrant (Range + MatchValue)
      ▼
Base vectorielle Qdrant ◄──── Mistral Embeddings
      │
      ▼
Contexte trouvé ? ──non──► Agent web (smolagents + Tavily)
      │ oui
      ▼
Mistral (LLM) ──► Réponse en streaming
      │
      ▼
Monitoring (SQLite) + Feedback utilisateur
```

Le filtrage temporel et géographique est exécuté **nativement par Qdrant**, avant la recherche vectorielle — pas de post-traitement Python sur les résultats. Voir le [changelog technique](docs/changelog_poc_to_mvp.md) pour le détail des choix d'architecture.

## Stack technique

| Composant | Technologie |
|---|---|
| LLM & Embeddings | Mistral AI (`mistral-medium`, `mistral-embed`) |
| Base vectorielle | Qdrant |
| Orchestration | LangChain (LCEL) |
| Interface | Streamlit |
| Recherche web | smolagents + Tavily |
| Monitoring | SQLite + dashboard Streamlit |
| Source de données | API OpenAgenda (via Opendatasoft) |
| Conteneurisation | Docker / Docker Compose |
| Évaluation | RAGAS |

## Installation

### Prérequis

- Python 3.13+
- [Poetry](https://python-poetry.org/)
- Docker & Docker Compose
- Une clé API [Mistral AI](https://console.mistral.ai/)
- Une clé API [Tavily](https://tavily.com/) (fallback web, quota gratuit mensuel)

### Mise en place

```bash
git clone <url-du-repo>
cd puls_events_rag

# Copier et remplir les variables d'environnement
cp .env.example .env
# → renseigner MISTRAL_API_KEY, TAVILY_API_KEY, etc.

# Installer les dépendances
poetry install
```

### Lancer avec Docker (recommandé)

```bash
docker compose up --build
```

- Application : [http://localhost:8501](http://localhost:8501)
- Dashboard monitoring : [http://localhost:8502](http://localhost:8502)
- Qdrant (interface d'administration) : [http://localhost:6333/dashboard](http://localhost:6333/dashboard)

### Construire l'index

Avant le premier lancement, la base vectorielle doit être peuplée :

```bash
poetry run python src/build_index.py
```

Ce script ingère les événements depuis OpenAgenda (région définie par `FILTER_REGION` dans `.env`), les nettoie, les découpe en chunks et les vectorise dans Qdrant.

## Utilisation

Une fois l'application lancée, pose une question en langage naturel :

```
Quels concerts à Paris ce mois-ci ?
et à Versailles ?
Quels sont les événements à venir en Corse ?
```

La sidebar permet d'indiquer manuellement une ville/région si la détection automatique par IP est incorrecte ou absente.

## Structure du projet

```
puls_events_rag/
├── src/
│   ├── app.py              # Interface Streamlit principale
│   ├── rag_chain.py         # Chaîne RAG : retriever, mémoire, filtres
│   ├── geo.py                # Détection géographique (villes, régions, IP)
│   ├── vectorization.py      # Découpage en chunks, client Qdrant
│   ├── preprocessing.py      # Nettoyage des données OpenAgenda
│   ├── data_ingestion.py     # Ingestion API (pagination, multi-région)
│   ├── build_index.py        # Script d'orchestration de l'indexation
│   ├── monitoring.py         # Logging des interactions (SQLite)
│   ├── dashboard.py          # Dashboard de monitoring
│   └── web_agent.py          # Agent de recherche web (smolagents + Tavily)
├── data/                     # Données et index (non versionné)
├── docs/                     # Documentation complémentaire
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Évaluation

La qualité du système est mesurée avec [RAGAS](https://github.com/explodinggym/ragas) sur un jeu de 30 questions fermées, construites directement depuis des chunks réels de la base.

| Métrique | POC | MVP |
|---|---|---|
| Faithfulness | 0.41 | **0.79** |
| Context Recall | 0.14 | **0.80** |
| Answer Correctness | 0.32 | **0.57** |

## Limites connues / Roadmap

- **Sessions non persistées** — la mémoire conversationnelle utilise un dictionnaire en mémoire (Redis prévu pour la production)
- **Monitoring SQLite** — adapté au MVP, PostgreSQL nécessaire au-delà d'une seule instance applicative
- **Indexation nationale** — le passage à la France entière nécessite une infrastructure Qdrant en cluster
- **Indexation incrémentale** — les identifiants de points sont déjà déterministes (pas de doublons en cas de réindexation), mais le filtrage sur les événements modifiés (`updatedat`) n'est pas encore implémenté
- **CI/CD et déploiement cloud** — architecture cible documentée (Scaleway), déploiement effectif non réalisé à ce stade
