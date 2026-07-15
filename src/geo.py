import requests
import unicodedata

# correspondance des noms de régions données > géolocalisation
REGIONS_FR = {
    "île-de-france": "Île-de-France",
    "ile-de-france": "Île-de-France",
    "auvergne-rhône-alpes": "Auvergne-Rhône-Alpes",
    "nouvelle-aquitaine": "Nouvelle-Aquitaine",
    "occitanie": "Occitanie",
    "hauts-de-france": "Hauts-de-France",
    "provence-alpes-côte d'azur": "Provence-Alpes-Côte d'Azur",
    "grand est": "Grand Est",
    "bretagne": "Bretagne",
    "pays de la loire": "Pays de la Loire",
    "normandie": "Normandie",
    "bourgogne-franche-comté": "Bourgogne-Franche-Comté",
    "centre-val de loire": "Centre-Val de Loire",
    "corse": "Corse",
}

# Normalise les noms des régions
def normaliser(texte: str) -> str:
    if not texte:              # gère None et chaîne vide
        return ""
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.lower().strip()


def detecter_localisation_ip() -> dict:
    """Détecte ville + région de l'utilisateur via son IP."""
    try:
        resp = requests.get( # Requête pour déterminer la localisation approximative à partir de l'IP
            "http://ip-api.com/json/?fields=status,regionName,city",
            timeout=3
        )
        data = resp.json()
        if data.get("status") == "success":
            region_brute = normaliser(data.get("regionName", "")) # normalise le nom de la région
            return { 
                "ville":  data.get("city") or None,
                "region": REGIONS_FR.get(region_brute) # cherche la correspondance des noms de régions
            }
    except requests.RequestException:
        pass
    return {"ville": None, "region": None}


def extraire_ville(question: str, villes_connues: set) -> str | None:
    """Détecte une ville connue mentionnée dans la question.
    Retourne la ville normalisée ou None."""
    q_norm = normaliser(question)
    candidates = [v for v in villes_connues if v in q_norm]
    if not candidates:
        return None
    # La plus longue gagne (évite que "paris" matche "cormeilles-en-parisis")
    return max(candidates, key=len)


def extraire_region(question: str) -> str | None:
    """Détecte une région française mentionnée dans la question.
    Retourne le nom officiel de la région ou None."""
    q_norm = normaliser(question)
    for cle, region in REGIONS_FR.items():
        if normaliser(cle) in q_norm:
            return region
    return None