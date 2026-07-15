# src/data_ingestion.py — version qui gère la France entière
import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

load_dotenv()

API_URL = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records/"

REGIONS_FRANCE = [
    "Île-de-France", "Auvergne-Rhône-Alpes", "Nouvelle-Aquitaine",
    "Occitanie", "Hauts-de-France", "Provence-Alpes-Côte d'Azur",
    "Grand Est", "Bretagne", "Pays de la Loire", "Normandie",
    "Bourgogne-Franche-Comté", "Centre-Val de Loire", "Corse"
]

today = datetime.now()
one_year_ago = today - timedelta(days=365)

# Compte le nombre d'évenements par région pour éviter de dépasser la tranche limite de 10000
def compter_resultats(region: str, date_min: str, date_max: str) -> int:
    where = f'location_region="{region}" AND firstdate_begin > "{date_min}" AND firstdate_begin <= "{date_max}"'
    params = {"lang": "fr", "limit": 1, "where": where}
    response = requests.get(API_URL, params=params)
    return response.json().get("total_count", 0)

def fetch_tranche(region: str, date_min: str, date_max: str) -> list:
    """Récupère tous les événements d'une région sur une fenêtre de dates donnée."""
    all_results = []
    offset = 0
    limit = 100 # par batch de 100

    while True:
        where = f'location_region="{region}" AND firstdate_begin > "{date_min}" AND firstdate_begin <= "{date_max}"' # limite géographique et temporelle de la requête
        params = {"lang": "fr", "limit": limit, "offset": offset, "where": where} # paramètres complets de la requête
        response = requests.get(API_URL, params=params) #envoie la requête sur l'API
        results = response.json().get("results", []) # parse les résultats au format json

        if not results:
            break

        all_results.extend(results) # ajoute les résultats obtenus
        offset += limit # passe au prochan batch 

        if offset >= 9900:  # sécurité, ne devrait jamais arriver si le découpage mensuel est correct
            print(f"    ⚠ Tranche {date_min}→{date_max} atteint la limite, résultats partiels")
            break

    return all_results


def generer_tranches_mensuelles(date_debut: datetime, date_fin: datetime) -> list:
    """Génère des paires (date_min, date_max) mois par mois. Permet de contourner la limite de l'API de 10000 résultats"""
    tranches = []
    courant = date_debut
    while courant < date_fin:
        suivant = min(courant + relativedelta(months=1), date_fin) # définit la période du jour actuel jusqu'au mois suivant
        tranches.append((courant.strftime("%Y-%m-%d"), suivant.strftime("%Y-%m-%d")))
        courant = suivant
    return tranches


def fetch_events_france(regions: list = None) -> dict:
    """Si `regions` est fourni, ne traite que ces régions-là.
    Sinon, traite REGIONS_FRANCE en entier."""
    all_results = []
    regions_a_traiter = regions if regions else REGIONS_FRANCE #Sélectionne la région choisie ou toutes les régions
    tranches = generer_tranches_mensuelles(one_year_ago, today + relativedelta(years=1)) #Génere les tranches mois par mois de 1 an en arrière jusqu'à 1 an dans le futur

    for region in regions_a_traiter:
        print(f"\n=== {region} ===")
        for date_min, date_max in tranches:
            total = compter_resultats(region, date_min, date_max) # Compte le nombre de résultat pour la région donnée, pour la période donnée
            if total == 0: # Si aucun résultat, on passe au suivant
                continue
            if total > 9500: # Si plus de 9500 résultats sur la tranche donnée on envoie une alerte
                print(f"  {date_min}→{date_max} : {total} (⚠ dépasse encore, résultats partiels)")
            resultats = fetch_tranche(region, date_min, date_max) # Récupère les résultats de la tranche donnée
            all_results.extend(resultats) # Append les résultats totaux
            print(f"  {date_min}→{date_max} : {len(resultats)} récupérés")

    print(f"\nTOTAL : {len(all_results)} événements")
    return {"results": all_results}