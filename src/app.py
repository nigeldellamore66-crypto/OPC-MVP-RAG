import streamlit as st
import uuid
import time
from rag_chain import build_rag_chain
from vectorization import get_qdrant_client
from geo import detecter_localisation_ip, REGIONS_FR
from monitoring import init_db, logger_interaction, logger_feedback
from web_agent import rechercher_evenements_web

# Initialisation de la DB de monitoring
init_db()

# Localisation utilisateur région + ville ( seulement au lancement de l'application)
if "localisation" not in st.session_state:
    st.session_state.localisation = detecter_localisation_ip()

# Définition de la sidebar de géolocalisation
with st.sidebar:
    st.subheader("Ma localisation")

    # Champ texte éditable prérempli avec la ville détectée
    ville_utilisateur = st.text_input(
        "Ma ville",
        value=st.session_state.localisation.get("ville") or "",
        placeholder="ex: Versailles"
    )

    regions_liste = sorted(set(REGIONS_FR.values()))
    region_detectee = st.session_state.localisation.get("region")
    index_defaut = regions_liste.index(region_detectee) if region_detectee in regions_liste else 0

    # Champ liste déroulante avec toutes les régions, avec la région détectée préselectionnée
    region_utilisateur = st.selectbox("Ma région", regions_liste, index=index_defaut)

    if st.session_state.localisation.get("ville"):
        st.caption(f"Détecté automatiquement : {st.session_state.localisation['ville']}")

# Session et chaîne RAG 
if "session_id" not in st.session_state: # Génere un UID pour chaque utilisateur/session
    st.session_state.session_id = str(uuid.uuid4())

if "chain" not in st.session_state: # Charge une fois la chaîne au lancement de l'application
    qdrant_client = get_qdrant_client()
    st.session_state.chain = build_rag_chain(qdrant_client, collection_name="puls_events_test_v2") # DEFINITION NOM COLLECTION QDRANT 

# Chat
if "messages" not in st.session_state: # Affiche le message de bienvenue lors du lancement d'une nouvelle session
    st.session_state.messages = [{"role": "assistant", "content": "Bonjour, je suis l'assistant virtuel de Puls-Events. Comment puis-je vous aider aujourd'hui?"}]

st.title("Assistant Virtuel de Puls-Events")

# Affichage des messages précédents
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# Dialogue
if prompt := st.chat_input("Comment puis-je vous aider?"):
    # Affiche le message de l'utilisateur
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt) # Champ texte permettant d'écrire la question

    # Réponse de l'assistant en streaming
    with st.chat_message("assistant"):
        debut = time.time()
        contexte_capture = []

        try:
            def stream_answer():
                """Générateur : émet les morceaux de réponse en streaming,
                capture le contexte au passage pour le monitoring."""
                for chunk in st.session_state.chain.stream( # invoque la chaîne LCEL en streaming
                    {
                        "question": prompt,
                        "ville_utilisateur": ville_utilisateur or None,
                        "region_utilisateur": region_utilisateur
                    },
                    config={"configurable": {"session_id": st.session_state.session_id}}
                ):
                    if isinstance(chunk, dict): # Vérifie si chaque chunk renvoyé contient du contexte ou de la réponse
                        if "context" in chunk:
                            contexte_capture.extend(chunk["context"]) # si il contient du contexte, on l'ajoute à la liste contexte
                        if "answer" in chunk:
                            yield chunk["answer"] # si il contient du answer, on l'affiche

            # Appelle la fonction de streaming ET retourne le texte complet
            response = st.write_stream(stream_answer())
            
            # Calcule la latence d'affichage pour le monitoring 
            duree_ms = (time.time() - debut) * 1000

            # Fallback web si la base locale n'a rien trouvé 
            if len(contexte_capture) == 0 or "je n'ai pas trouvé" in response.lower(): # Si 0 résultats dans le retriever, ou si mistral renvoie "je n'ai pas trouvé"
                with st.spinner("Recherche sur le web..."):
                    resultat_web = rechercher_evenements_web( # Appelle la fonction de recherche web avec la question et le contexte 
                        question=prompt,
                        ville=ville_utilisateur,
                        region=region_utilisateur
                    )
                if resultat_web: # Affiche le résultat obtenu
                    st.info("Résultats issus d'une recherche web (hors base Puls-Events) :")
                    st.write(resultat_web)
                    response = response + "\n\n[Recherche web] " + resultat_web
                    
            # Log de l'interaction complète dans la base SQLLite pour le monitoring
            interaction_id = logger_interaction(
                session_id=st.session_state.session_id,
                question=prompt,
                reponse=response,
                nb_chunks=len(contexte_capture),
                ville=ville_utilisateur,
                duree_ms=duree_ms
            )
            st.session_state.derniere_interaction_id = interaction_id

        except Exception as e:
            st.error(f"Erreur lors de la génération de la réponse: {e}")
            response = "Je suis désolé, j'ai rencontré un problème. Veuillez réessayer."
            st.write(response)

        # Boutons feedback
        if "derniere_interaction_id" in st.session_state:
            col1, col2, _ = st.columns([1, 1, 8])
            iid = st.session_state.derniere_interaction_id
            with col1:
                st.button("👍", key=f"up_{iid}",
                          on_click=logger_feedback, args=(iid, 1)) # Envoie le feedback dans la base de monitoring sur l'interaction loggé auaparavant
            with col2:
                st.button("👎", key=f"down_{iid}",
                          on_click=logger_feedback, args=(iid, 0))

    st.session_state.messages.append({"role": "assistant", "content": response}) # On ajoute la réponse finale de l'assistant à la liste messages