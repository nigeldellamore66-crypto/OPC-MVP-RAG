import json
from datetime import datetime
from geo import normaliser
import re
from bs4 import BeautifulSoup

# Timestamp des dates nécessaire pour filtrage natif Qdrant
def date_vers_timestamp(date_str: str) -> int:
    if not date_str:
        return 0
    try:
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())
    except ValueError:
        return 0

def preprocess_events(events):
    # Appel de la fonction de nettoyage pour chaque événement et filtrage des événements invalides
    cleaned_events = []
    for result in events.get("results", []):
        cleaned_event = clean_event(result)
        if cleaned_event:
            cleaned_events.append(cleaned_event)

    # Sauvegarde des fichier nettoyés en json
    with open("data/events_clean.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_events, f, ensure_ascii=False, indent=2)

    return cleaned_events

def clean_event(event):

    # Si pas de description ou pas de titre on ne récupère pas l'évenement
    if not event.get("longdescription_fr") or not event.get("title_fr"):
        return None

    # Parse les timings une seule fois
    timings_info = parse_timings(event.get("timings", "[]"))
    
    # Génère un résumé temporel adapté au nombre d'occurrences
    timings_summary = summarize_timings(timings_info)

    cleaned_event = {
        "text": (
            f"L'événement {event.get('title_fr')} "
            f"a lieu au {event.get('location_name')} "
            f"dans la ville de {event.get('location_city')}. "
            f"{timings_summary}. "
            f"Description : {clean_html(event.get('longdescription_fr', ''))}"
        ),
        "metadata": {
            "title": event.get("title_fr", ""),
            "city": normaliser(event.get("location_city", "")),
            "region": event.get("location_region", ""),
            "location": event.get("location_name", ""),
            "date_debut": timings_info["date_debut"],
            "date_fin": timings_info["date_fin"],
            "date_debut_ts": date_vers_timestamp(timings_info["date_debut"]),
            "date_fin_ts": date_vers_timestamp(timings_info["date_fin"]),
            "nb_occurrences": timings_info["nb_occurrences"],
            "firstdate": event.get("firstdate_begin", ""),
            "uid": event.get("uid", ""),
        }
    }
    return cleaned_event


def parse_timings(timings_str):
    #Extrait les infos temporelles structurées des timings.
    if not timings_str or timings_str == "[]":
        return {
            "date_debut": "",
            "date_fin": "",
            "nb_occurrences": 0,
            "occurrences": [],
        }
    
    timings = json.loads(timings_str)
    if not timings:
        return {
            "date_debut": "",
            "date_fin": "",
            "nb_occurrences": 0,
            "occurrences": [],
        }
    
    occurrences = []
    for t in timings:
        begin = datetime.fromisoformat(t["begin"])
        end = datetime.fromisoformat(t["end"])
        occurrences.append({"begin": begin, "end": end})
    
    return {
        "date_debut": min(o["begin"] for o in occurrences).strftime("%Y-%m-%d"),
        "date_fin": max(o["end"] for o in occurrences).strftime("%Y-%m-%d"),
        "nb_occurrences": len(occurrences),
        "occurrences": occurrences,
    }

MOIS_FR = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "août",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
}

def summarize_timings(timings_info):
    nb = timings_info["nb_occurrences"]
    
    if nb == 0:
        return "Dates non précisées"
    
    if nb == 1:
        o = timings_info["occurrences"][0]
        mois = MOIS_FR[o['begin'].month]
        annee = o['begin'].year
        return (
            f"Date : le {o['begin'].strftime('%d/%m/%Y')} "
            f"({mois} {annee}) "
            f"de {o['begin'].strftime('%Hh%M')} à {o['end'].strftime('%Hh%M')}"
        )
    
    if nb <= 10:
        formatted = []
        for o in timings_info["occurrences"]:
            mois = MOIS_FR[o['begin'].month]
            annee = o['begin'].year
            formatted.append(
                f"le {o['begin'].strftime('%d/%m/%Y')} ({mois} {annee})"
            )
        return f"Dates : {' ; '.join(formatted)}"
    
    # Beaucoup d'occurrences : on liste les mois couverts
    date_debut_dt = datetime.strptime(timings_info["date_debut"], "%Y-%m-%d")
    date_fin_dt = datetime.strptime(timings_info["date_fin"], "%Y-%m-%d")
    
    mois_couverts = set()
    for o in timings_info["occurrences"]:
        mois_couverts.add(f"{MOIS_FR[o['begin'].month]} {o['begin'].year}")
    mois_str = ", ".join(sorted(mois_couverts))
    
    return (
        f"Événement récurrent : {nb} occurrences "
        f"du {date_debut_dt.strftime('%d/%m/%Y')} "
        f"au {date_fin_dt.strftime('%d/%m/%Y')}. "
        f"Mois concernés : {mois_str}"
    )


def clean_html(text):
    # Implémentation d'une fonction de nettoyage HTML avec BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    clean = soup.get_text(separator=" ")
    clean = re.sub(r'\s+', ' ', clean)  # remplace tous les espaces/\n multiples par un seul espace
    return clean.strip()