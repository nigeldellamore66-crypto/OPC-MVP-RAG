# Puls-Events — Changelog technique POC → MVP

Résumé exhaustif de toutes les modifications apportées au code depuis le POC validé.

---

## 1. `rag_chain.py` — la chaîne RAG (fichier le plus modifié)

### Mémoire conversationnelle (nouveau)
- `session_store` (dict Python) + `get_session_history(session_id)` : historique par session, un `ChatMessageHistory` par utilisateur
- `format_history()` : formate les 6 derniers messages (3 échanges) pour le prompt — limité volontairement pour maîtriser la latence et le coût token
- Chaîne enveloppée dans `RunnableWithMessageHistory` (LangChain), avec `session_id` unique par utilisateur généré côté `app.py`

### Filtre temporel en Python (nouveau, remplace le raisonnement du LLM)
- `extraire_criteres_temporels(question)` : détecte mois (`MOIS_FR`), année (regex `20\d{2}`), intention futur/passé (`MOTS_FUTUR`/`MOTS_PASSE`), et l'expression relative "ce mois(-ci)"
- `filtrer_par_dates(docs_et_scores, criteres, k)` : filtre les documents selon `date_debut`/`date_fin` en Python — **le LLM ne fait plus aucun raisonnement sur les dates**, il présente un contexte déjà filtré
- **Règle du futur par défaut** : si aucun critère temporel n'est détecté, `intention = "futur"` est forcé — un assistant événementiel doit montrer l'à-venir par défaut
- **Héritage temporel depuis l'historique** : si la question de suivi ne contient aucun critère temporel, le retriever va chercher le dernier critère détecté dans les questions précédentes de la session (corrige le bug où "et à Versailles ?" perdait le "ce mois-ci" de la question précédente)

### Contexte géographique (nouveau)
- Détection ville/région dans la question (`extraire_ville`, `extraire_region`, déplacées dans `geo.py`)
- Priorité : ville/région mentionnée dans la question > profil utilisateur (sidebar/IP)
- Logique d'entonnoir : filtre ville → repli sur région si aucun résultat exact
- Récupéré depuis l'historique quand la question de suivi ne précise pas de localisation

### Retriever intelligent — évolution en plusieurs étapes
- v1 : `k=20` fixe
- v2 : passage à `k=300` (recherche large en amont, filtrage Python en aval) pour compenser les questions de suivi pauvres en mots-clés (ex. "et à Versailles ?")
- v3 (final, avec Qdrant) : filtrage natif côté serveur via `Filter`/`FieldCondition`/`Range`/`MatchValue` — le `k` redescend à une recherche ciblée avec `limit=12`, plus besoin de sur-échantillonner puisque Qdrant filtre **avant** de chercher

### Migration FAISS → Qdrant
- `construire_filtre_qdrant(criteres, ville, region)` : traduit les critères Python en filtre Qdrant natif (`Range` sur les dates, `MatchValue` sur ville/région)
- `construire_index_villes_qdrant(client, collection_name)` : remplace `construire_index_villes(vectorstore)` — récupère les villes connues via `client.scroll()` au lieu d'un `similarity_search` FAISS
- `build_rag_chain()` prend désormais un `qdrant_client` + `collection_name` en paramètres au lieu d'un `vectorstore` FAISS
- Le retriever appelle `qdrant_client.query_points(query=vecteur, query_filter=..., limit=12)` au lieu de `vectorstore.similarity_search_with_score()`
- Repli ville → région géré par un deuxième appel `query_points` avec un filtre élargi si le premier ne retourne rien

### Modèle LLM et paramètres
- Test successif : `mistral-large` (trop lent, ~12s) → `mistral-small` (rapide mais incohérences sur les règles conditionnelles) → **`mistral-medium`** retenu (compromis latence/fiabilité)
- `max_tokens` ajouté et ajusté (1000 → 1200 → 1500) pour borner la longueur de génération (latence + éviter les réponses tronquées en milieu de liste)
- `temperature=0` maintenu (déterminisme)

### Streaming
- `.invoke()` remplacé par `.stream()` dans `app.py`, avec un générateur qui filtre les chunks `dict` émis par la chaîne (`context` capturé pour le monitoring, `answer` yield pour l'affichage progressif)

---

## 2. `geo.py` — nouveau fichier

- `normaliser(texte)` : suppression accents + minuscules, **avec garde contre `None`** (bug corrigé : `unicodedata.normalize` plantait sur les métadonnées `city=None`, présent aussi bien en local qu'en évaluation RAGAS)
- `detecter_localisation_ip()` : géolocalisation via `ip-api.com`, retourne `{ville, region}`
- `REGIONS_FR` : dictionnaire de mapping nom de région → nom officiel
- `construire_index_villes(vectorstore)` : liste des villes connues (version FAISS, `similarity_search` large)
- `extraire_ville(question, villes_connues)` : matching de la ville la plus longue présente dans la question (évite qu'"paris" matche dans "Cormeilles-en-Parisis")
- `extraire_region(question)` : matching de région dans la question

---

## 3. `monitoring.py` — nouveau fichier

- SQLite (`data/monitoring.db`), chemin **absolu** ancré sur `Path(__file__).parent.parent` (bug corrigé : chemin relatif erroné selon le répertoire de lancement)
- `init_db()` : table `interactions` (session_id, question, réponse, nb_chunks, ville, durée, `est_echec` calculé par détection de phrases-clés, `feedback`)
- `logger_interaction()` : log automatique de chaque échange
- `logger_feedback()` : mise à jour du feedback 👍/👎 via callback `on_click` (évite le re-run intempestif de Streamlit qu'un `if st.button()` classique provoquerait)
- `charger_interactions()` : pour le dashboard

## 3bis. `dashboard.py` — nouveau fichier

- Métriques : nombre d'interactions, taux d'échec, latence p50/p95, taux de feedback positif
- Alertes par seuil (taux d'échec > 10%, latence p95 > 5s, feedback < 75%)
- Tendances par jour (graphes interactions/échecs/latence)
- Table des dernières questions en échec (source pour enrichir le dataset d'évaluation)

---

## 4. `web_agent.py` — nouveau fichier (recherche web smolagents)

- `CodeAgent` (smolagents) + `LiteLLMModel` pointant sur `mistral-medium`
- Outil de recherche : **DuckDuckGo abandonné** (HTTP 403 aléatoires, non fiable en usage applicatif) → **Tavily** adopté via une classe `TavilySearchTool(Tool)` custom, intégrée nativement dans smolagents
- `rechercher_evenements_web(question, ville, region)` :
  - Injecte la date du jour dans la consigne (corrige le bug où l'agent datait ses réponses de "juin 2025" au lieu de l'année courante)
  - Garde-fou explicite : mot-clé `ECHEC_RECHERCHE` si rien de fiable trouvé
- Déclenchement dans `app.py` uniquement si le contexte local est vide ou si la réponse contient "je n'ai pas trouvé" (fallback, pas systématique)
- `max_steps=3` sur l'agent (limite les itérations, donc le coût et la latence)

---

## 5. `app.py`

- Ajout `uuid` : `session_id` unique par utilisateur, généré une fois par session Streamlit
- Sidebar localisation : `ville_utilisateur` (text_input, pré-rempli par géoloc IP) + `region_utilisateur` (selectbox), déclarée **avant** le chat (piège Streamlit : l'ordre d'exécution du script compte)
- Passage de `ville_utilisateur`/`region_utilisateur` dans l'`invoke`/`stream` de la chaîne
- Remplacement du bloc `generer_reponse()` classique par un générateur `stream_answer()` utilisé avec `st.write_stream()` — affichage progressif + capture du contexte pour le monitoring dans le même passage
- Ajout du fallback web (import `rechercher_evenements_web`) après le streaming
- Ajout du logging monitoring (`logger_interaction`) et des boutons feedback (`on_click=logger_feedback`)
- **Changement final (Qdrant)** : `build_vectorstore()` (FAISS) remplacé par `get_qdrant_client()`, passé à `build_rag_chain(qdrant_client, collection_name="puls_events")`

---

## 6. `vectorization.py`

- `chunk_size` : 512 (implicite/défaut) → **800**, après avoir diagnostiqué que RAGAS remontait des contextes tronqués en plein mot, faussant l'évaluation (et probablement dégradant légèrement les réponses réelles)
- Ajout de `get_qdrant_client()` (mode serveur `host="qdrant"`/`"localhost"` selon le contexte d'exécution, remplace le mode fichier local `path=...` qui plafonne officiellement à 20 000 points selon l'avertissement de Qdrant lui-même)
- `build_qdrant_store()` : création de collection + vectorisation par lots (`BATCH_SIZE`), avec retry sur erreurs 429/réseau et pause entre lots

---

## 7. `preprocessing.py`

- `clean_event()` : la métadonnée **`city` est désormais normalisée à l'indexation** (`normaliser(event.get("location_city", ""))`) plutôt que normalisée à la volée à chaque comparaison — nécessaire car le filtrage Qdrant natif (`MatchValue`) fait une comparaison exacte, contrairement à l'ancien code FAISS qui appelait `normaliser()` des deux côtés à chaque requête
- Le champ `text` (affiché à l'utilisateur) reste construit depuis les données brutes, donc la casse d'origine ("Saint-Cloud") est préservée à l'affichage malgré la normalisation de la métadonnée de filtrage
- Fonction `parse_timings()`/`summarize_timings()` : compression des dates multiples en résumé texte + métadonnées `date_debut`/`date_fin`/`nb_occurrences` structurées (évite les listes de 100+ dates brutes qui perturbaient l'embedding — c'était un des diagnostics du POC)

---

## 8. `data_ingestion.py`

- Passage d'une ingestion mono-région (`FILTER_REGION` unique, limite `max_events=15000` non fiable) à une **ingestion multi-région pour la France entière**
- `compter_resultats(region, date_min, date_max)` : requête légère (`limit=1`) pour connaître le volume avant de tout télécharger
- Découpage en **tranches mensuelles** par région (`generer_tranches_mensuelles`) : contourne la limite de 10 000 résultats de l'API (`offset + limit ≤ 10000`) — validé sur Nouvelle-Aquitaine, la région la plus dense (pic mensuel 5791, largement sous la limite)
- `fetch_tranche()` : pagination classique à l'intérieur d'une tranche, avec pause (`time.sleep(0.15)`) entre les requêtes

---

## 9. `build_index.py`

- Script d'orchestration réécrit : `build_vectorstore()` (FAISS, une ligne) remplacé par toute la logique Qdrant (connexion serveur, création de collection conditionnelle, vectorisation par lots avec retry et reprise sur checkpoint)
- Ajout d'un mécanisme de **checkpoint** (`data/qdrant_checkpoint.txt`) : sauvegarde la progression après chaque lot réussi, permet de reprendre une indexation interrompue par une coupure réseau sans tout recommencer (`encoding="utf-8-sig"` pour tolérer le BOM ajouté par PowerShell lors de la création manuelle du fichier)

---

## 10. Infrastructure — Docker

### `Dockerfile`
- Image `python:3.13-slim`, Poetry pour l'installation des dépendances
- `poetry install --no-root` (le projet lui-même n'est pas packagé, seules ses dépendances le sont)
- Une seule image sert à la fois pour l'app et le dashboard (différenciés par la commande dans `docker-compose.yml`)

### `docker-compose.yml`
- Service `app` (Streamlit, port 8501)
- Service `dashboard` (Streamlit, port 8502, même image, commande différente pointant vers `src/dashboard.py`)
- Service `qdrant` (image officielle `qdrant/qdrant`, port 6333, volume `data/qdrant_storage` dédié) — ajouté après avoir constaté que le mode fichier local de Qdrant n'est pas recommandé au-delà de 20 000 points
- Le service `ingestion` (job cron) a été retiré du compose local — la planification sera gérée par le cloud (Scaleway Serverless Jobs) au déploiement, pas par un cron interne au conteneur

### `.dockerignore`
- Exclusion de `data/` (montée en volume, jamais figée dans l'image), `.venv/`, `__pycache__/`, `.git/`

---

## 11. Nettoyage des dépendances (`pyproject.toml`)

Retirés (résidus ou plus utilisés) :
- `langchain` (jamais importé directement, seuls les sous-packages `langchain-core`/`langchain-community`/`langchain-mistralai` sont utilisés)
- `datetime` (module natif Python, jamais un package à installer)
- `ragas`, `datasets` (l'évaluation RAGAS tourne finalement dans un environnement Python séparé, hors Poetry, à cause d'un conflit de dépendances irréconciliable avec `instructor`/`mistralai` — voir section évaluation)
- `duckduckgo-search` (abandonné au profit de Tavily)

Conservés/ajoutés : `qdrant-client`, `tavily-python`, `smolagents[litellm]`, `python-dateutil`

---

## 12. Évaluation RAGAS — méthodologie

### Dataset
- v1 (POC) : questions ouvertes ("événements gratuits en mai ?"), ground_truth incomplets faute de pouvoir annoter 70+ réponses possibles par question → context_recall ininterprétable (0.14)
- v2 (MVP) : reconstruction complète — 25 questions **fermées** construites depuis des chunks réels échantillonnés aléatoirement (une question = une réponse vérifiable, contexte de référence complet et non tronqué), + 5 questions "sans réponse"/hors-sujet
- Alignement questions/logique métier : les événements futurs de l'échantillon ont des questions **sans date** (le système les trouve via le futur-par-défaut) ; les événements passés ont une **date explicite** dans la question (déclenche la détection temporelle et lève le filtre futur) — sans cet alignement, le premier essai donnait un context_recall de 0.20 à cause d'une incompatibilité entre dataset et comportement voulu du système, pas d'un vrai défaut de retrieval

### Environnement d'exécution
- Conflit de dépendances bloquant entre `ragas`, `instructor` et `mistralai` v2 dans l'environnement Poetry du projet
- Résolu en installant RAGAS + `mistralai` v1 dans le **Python global** de la machine (hors Poetry)
- `evaluator_llm`/`evaluator_embeddings` forcés sur `LangchainLLMWrapper`/`LangchainEmbeddingsWrapper` (Mistral) pour éviter que RAGAS retombe sur OpenAI par défaut (clé absente)
- Gestion du rate limit Mistral (429) par retry avec pause (5s entre requêtes, 30s en cas de 429, jusqu'à 3 tentatives)

### Résultats

| Métrique | POC | MVP (chunks 512, tronqués) | MVP final (chunks 800) |
|---|---|---|---|
| faithfulness | 0.41 | 0.75 | **0.79** |
| context_recall | 0.14 | 0.80 | **0.80** |
| answer_correctness | 0.32 | 0.57 | **0.57** |

---

## Synthèse des causes racines corrigées

| Symptôme observé au POC | Cause racine identifiée | Correction |
|---|---|---|
| Dates incohérentes, événements passés présentés comme futurs | Le LLM raisonnait lui-même sur les dates | Filtrage temporel déplacé en Python, le LLM ne fait plus que présenter |
| Context_recall très faible (0.14) | Chunks avec listes de 100+ dates brutes perturbant l'embedding + dataset d'évaluation à questions trop ouvertes | Compression des dates en résumé + métadonnées structurées ; dataset reconstruit avec questions fermées |
| Incohérence sur les questions de suivi ("et à Versailles ?") | La requête FAISS sur la question seule est trop pauvre sémantiquement | k de recherche élargi, puis héritage explicite des critères depuis l'historique |
| Latence élevée (~12s) | Modèle trop gros, contexte trop large, pas de streaming | Passage à mistral-medium, réduction des chunks envoyés, `max_tokens` borné, streaming ajouté |
| Résultats de recherche web non fiables | DuckDuckGo bloque les requêtes programmatiques (403) | Migration vers Tavily (API avec clé, quota gratuit mensuel renouvelé) |
| Agent web halluciné en cas d'échec | Aucun garde-fou explicite contre l'improvisation | Mot-clé `ECHEC_RECHERCHE` + détection de marqueurs d'improvisation |
| FAISS non scalable pour la France entière | Pas de filtrage natif sur métadonnées, tout le filtrage se fait en Python après une recherche large | Migration vers Qdrant, filtrage natif côté serveur avant la recherche vectorielle |
| Limite API Opendatasoft à 10 000 résultats | Pagination simple insuffisante à l'échelle nationale | Découpage par région puis par mois, avec comptage préalable |
