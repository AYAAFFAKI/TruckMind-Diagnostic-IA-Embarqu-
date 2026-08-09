# ============================================================
# Projet : AI Truck Diagnostic Database — VERSION 9.5
# Correction par rapport à V9.4 :
#   → Le CSV truckmind_dataset_complet.csv contient des colonnes
#     qui étaient collectées lors de la génération (Employe_ID,
#     Employe_Nom, Departement, Poste, Trajet_ID, Niveau_Risque,
#     Historique_Pannes, Facteur_Age) mais QUI N'ÉTAIENT PAS
#     EXPLOITÉES par le script V9.4 (perte d'information).
#   → V9.5 ajoute :
#       1. Table employes (référentiel Finance/Logistique, 25
#          employés) + FK employe_id dans trips
#       2. trips.trajet_id_externe : conserve le Trajet_ID
#          original du CSV pour traçabilité
#       3. maintenance.niveau_risque + maintenance.historique_pannes
#          : deux colonnes CSV utiles au RAG, désormais stockées
#       4. vehicules.facteur_age : colonne CSV désormais stockée
#       5. query_vehicle_full() affiche le nom du responsable
#          Finance/Logistique par trajet
# Auteure : AFFAKI Aya — EST Tétouan
# ============================================================

import pandas as pd
import sqlite3
import os
import hashlib

# --- Connexion à la nouvelle base de données SQLite ---
script_dir = os.path.dirname(os.path.abspath(__file__))
db_dir = script_dir
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, "truckmind_v2.db")

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
cursor = conn.cursor()
print(f" Base de données connectée à : {db_path}")

# ============================================================
# CRÉATION DES TABLES
# ============================================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS vehicules (
    vehicule_id           TEXT PRIMARY KEY,
    annee_fabrication     INTEGER,
    heures_utilisation    INTEGER,
    capacite_charge_t     REAL,
    categorie_age         TEXT,
    facteur_age           REAL,
    valeur_achat_mad      REAL,
    valeur_actuelle_mad   REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS chauffeurs (
    chauffeur_id             TEXT PRIMARY KEY,
    nom                      TEXT,
    experience_annees        REAL,
    permis_numero            TEXT,
    permis_categorie         TEXT,
    permis_date_expiration   TEXT,
    salaire_base_mensuel_mad REAL,
    prime_activite_mad       REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS employes (
    employe_id    TEXT PRIMARY KEY,
    nom           TEXT,
    departement   TEXT,
    poste         TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS routes (
    route_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    route_nom        TEXT UNIQUE,
    distance_km      REAL,
    duree_estimee_h  REAL,
    type_itineraire  TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS knowledge (
    dtc      TEXT PRIMARY KEY,
    symptome TEXT,
    systeme  TEXT,
    piece    TEXT,
    gravite  TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS thresholds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parametre        TEXT NOT NULL,
    colonne_csv      TEXT,
    valeur_min       REAL,
    valeur_max       REAL,
    valeur_critique  REAL,
    sens_critique    TEXT,          -- 'bas' = critique si valeur <= seuil, 'haut' = critique si valeur >= seuil
    unite            TEXT,
    lampe            TEXT,
    niveau_alerte    TEXT,
    action           TEXT,
    source           TEXT,
    UNIQUE(parametre, niveau_alerte)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS maintenance (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicule_id            TEXT,
    dtc                    TEXT,
    date                   TEXT,
    action                 TEXT,
    etat_freins            TEXT,
    qualite_huile          REAL,
    anomalie_detectee      INTEGER,
    entretien_necessaire   INTEGER,
    score_predictif        REAL,
    niveau_risque          TEXT,
    historique_pannes      INTEGER,
    temperature_moteur     REAL,
    pression_pneus         REAL,
    consommation_carburant REAL,
    etat_batterie          REAL,
    niveaux_vibration      REAL,
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(vehicule_id),
    FOREIGN KEY (dtc)         REFERENCES knowledge(dtc)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS maintenance_alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    maintenance_id   INTEGER NOT NULL,
    threshold_id     INTEGER NOT NULL,
    valeur_mesuree   REAL,
    depassement      TEXT,
    FOREIGN KEY (maintenance_id) REFERENCES maintenance(id),
    FOREIGN KEY (threshold_id)   REFERENCES thresholds(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS trips (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    trajet_id_externe        TEXT,
    vehicule_id              TEXT,
    chauffeur_id             TEXT,
    employe_id               TEXT,
    route_id                 INTEGER,
    date                     TEXT,
    charge_reelle_t          REAL,
    type_marchandise         TEXT,
    facteur_marchandise      REAL,
    marchandise_dangereuse   INTEGER,
    conditions_meteo         TEXT,
    conditions_route         TEXT,
    delais_livraison_h       REAL,
    distance_estimee_km      REAL,
    carburant_estime_litres  REAL,
    cout_carburant_mad       REAL,
    revenu_estime_mad        REAL,
    impact_efficacite        REAL,
    FOREIGN KEY (vehicule_id)  REFERENCES vehicules(vehicule_id),
    FOREIGN KEY (chauffeur_id) REFERENCES chauffeurs(chauffeur_id),
    FOREIGN KEY (employe_id)   REFERENCES employes(employe_id),
    FOREIGN KEY (route_id)     REFERENCES routes(route_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS fleet_costs (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicule_id                TEXT,
    cout_entretien_mad         REAL,
    cout_carburant_total_mad   REAL,
    valeur_achat_mad           REAL,
    valeur_actuelle_mad        REAL,
    rentabilite_nette_mad      REAL,
    temps_arret_entretien_h    REAL,
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(vehicule_id)
)
""")

print(" 9 tables créées (dont employes) avec relations FK.")

# ============================================================
# REMPLISSAGE DE LA TABLE thresholds
# ============================================================

thresholds_data = [
    # (parametre, colonne_csv, v_min, v_max, v_critique, sens_critique, unite, lampe, niveau_alerte, action, source)

    ("Température Moteur",       "temperature_moteur",    None,  100.0,  None, None,    "°C",    "JAUNE", "SURVEILLANCE",    "Surveiller — risque de surchauffe",                   "Manuel Volvo FH/FM p.5"),
    ("Température Moteur",       "temperature_moteur",    None,  105.0,  None, None,    "°C",    "ROUGE", "ARRÊT IMMÉDIAT",  "Arrêter le moteur immédiatement — refroidir 10-15 min", "Manuel Volvo FH/FM p.24"),

    ("Pression Pneus",           "pression_pneus",        100.0, 120.0,  None, None,    "PSI",   "VERT",    "NORMAL",          "Pression dans la plage normale (100–120 PSI)",         "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",           "pression_pneus",         90.0,  None,  None, None,    "PSI",   "JAUNE", "SURVEILLANCE",    "Pression basse — vérifier les pneus avant départ",     "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",           "pression_pneus",         None,  None,   75.0, "bas",  "PSI",   "ROUGE", "ARRÊT IMMÉDIAT",  "Pression critique — risque d'éclatement",               "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus Haute",     "pression_pneus",         None,  125.0,  None, None,   "PSI",   "ROUGE", "ARRÊT IMMÉDIAT",  "Surpression — risque d'éclatement à chaud",             "Norme poids-lourd Volvo FH/FM"),

    ("Qualité Huile",            "qualite_huile",          40.0,  None,   None, None,   "%",     "JAUNE", "SURVEILLANCE",    "Huile dégradée — planifier vidange sous 30 jours",     "Manuel Volvo FH/FM p.1"),
    ("Qualité Huile",            "qualite_huile",          None,  None,   20.0, "bas",   "%",     "ROUGE", "ARRÊT IMMÉDIAT",  "Huile très dégradée — vidange immédiate obligatoire",   "Manuel Volvo FH/FM p.1"),

    ("État Batterie",            "etat_batterie",          30.0,  None,   None, None,   "%",     "JAUNE", "SURVEILLANCE",    "Batterie faible — vérifier l'alternateur",              "Manuel Volvo FH/FM p.84"),
    ("État Batterie",            "etat_batterie",          None,  None,   15.0, "bas",  "%",     "ROUGE", "ARRÊT IMMÉDIAT",  "Batterie critique — risque de panne démarrage",          "Manuel Volvo FH/FM p.84"),

    ("Consommation Carburant",   "consommation_carburant", None,  35.0,   None, None,   "L/100km","JAUNE","SURVEILLANCE",    "Consommation anormale — vérifier injection/filtre",    "Manuel Volvo FH/FM p.1"),
    ("Consommation Carburant",   "consommation_carburant", None,  None,   45.0, "haut", "L/100km","ROUGE","ARRÊT IMMÉDIAT",  "Consommation critique — diagnostic immédiat requis",    "Manuel Volvo FH/FM p.1"),

    ("Niveaux Vibration",        "niveaux_vibration",      None,   8.0,   None, None,   "mm/s",  "JAUNE", "SURVEILLANCE",    "Vibrations anormales — vérifier roues et suspension",  "Diagnostic standard Volvo"),
    ("Niveaux Vibration",        "niveaux_vibration",      None,   None,  12.0, "haut", "mm/s",  "ROUGE", "ARRÊT IMMÉDIAT",  "Vibrations critiques — risque de défaillance",          "Diagnostic standard Volvo"),

    ("Score Prédictif",          "score_predictif",        None,   0.5,   None, None,   "score", "JAUNE", "SURVEILLANCE",    "Risque modéré — planifier entretien sous 15 jours",    "Modèle prédictif TruckMind"),
    ("Score Prédictif",          "score_predictif",        None,   None,   0.8, "haut", "score", "ROUGE", "ARRÊT IMMÉDIAT",  "Risque critique — entretien immédiat obligatoire",      "Modèle prédictif TruckMind"),

    ("Vitesse TCS",              None,                     None,  40.0,   None, None,   "km/h",  "VERT",    "NORMAL",
     "TCS actif comme frein différentiel automatique à vitesse < 40 km/h",
     "Manuel Volvo FH/FM p.32 (TCS)"),

    ("Pression Frein Stationnement", None,                  5.0,  None,   None, None,   "bar",   "ROUGE", "ARRÊT IMMÉDIAT",
     "Pression insuffisante — appuyer valve verrouillage pour désengager",
     "Manuel Volvo FH/FM p.33"),

    ("Intervalle Vidange Huile (km)",  None,                None, None, 30000.0, "haut", "km",    "JAUNE", "SURVEILLANCE",
     "Vidange obligatoire tous les 30 000 km OU 12 mois — la première échéance prime",
     "Manuel Volvo FH/FM p.1 (DUAL CONDITIONS)"),
    ("Intervalle Vidange Huile (mois)", None,               None, None,   12.0, "haut", "mois",  "JAUNE", "SURVEILLANCE",
     "Vidange obligatoire tous les 12 mois OU 30 000 km — la première échéance prime",
     "Manuel Volvo FH/FM p.1 (DUAL CONDITIONS)"),

    ("Température Réfrigérant Démarrage", None,             50.0, None,   None, None,   "°C",    "JAUNE", "SURVEILLANCE",
     "Attendre que le réfrigérant soit > 50°C avant de solliciter le moteur",
     "Manuel Volvo FH/FM p.24"),

    ("Régime Ralenti",           None,                     550.0, 650.0,  None, None,   "tr/min", "VERT",   "NORMAL",
     "Régime de ralenti normal entre 550 et 650 tr/min",
     "Manuel Volvo FH/FM p.25"),
]

cursor.executemany("""
INSERT OR IGNORE INTO thresholds
    (parametre, colonne_csv, valeur_min, valeur_max, valeur_critique, sens_critique,
     unite, lampe, niveau_alerte, action, source)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", thresholds_data)

nb_thresholds = cursor.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0]
print(f" Table thresholds : {nb_thresholds} seuils techniques.")

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def safe_get(row, column, default_value):
    if column in row and pd.notna(row[column]):
        return row[column]
    return default_value

def detect_system(description):
    desc = str(description).lower()
    if "air" in desc:        return "admission"
    elif "temp" in desc:     return "refroidissement"
    elif "press" in desc:    return "capteur pression"
    elif "inject" in desc:   return "injection"
    elif "allumage" in desc: return "allumage"
    elif "abs" in desc:      return "freinage ABS"
    elif "vitesse" in desc:  return "transmission"
    elif "ralenti" in desc:  return "gestion moteur"
    else:                    return "moteur"

def detect_piece(description):
    desc = str(description).lower()
    if "capteur" in desc:                                          return "capteur"
    elif "injecteur" in desc or "inject" in desc:                  return "injecteur"
    elif "bobine" in desc:                                         return "bobine"
    elif "bougie de préchauffage" in desc:                         return "bougie de préchauffage"
    elif "allumage" in desc or "raté" in desc or "misfire" in desc or "spark" in desc or "ignition" in desc: return "bougie / bobine"
    elif "cylindre" in desc or "contribution" in desc:             return "injecteur cylindre"
    elif "calage" in desc or "référence" in desc or "rotor" in desc or "cam " in desc or "synchronization" in desc: return "distribution moteur"
    elif "catalyt" in desc or "catalys" in desc:                   return "catalyseur"
    elif "évaporat" in desc or "vacuum" in desc or "fuiteage" in desc: return "système antipollution"
    elif "exhaust" in desc or "échappement" in desc:               return "système échappement"
    elif "egr" in desc:                                            return "vanne EGR"
    elif "ralenti" in desc:                                        return "régulateur ralenti"
    elif "fan" in desc or "ventilateur" in desc:                   return "ventilateur refroidissement"
    elif "throttle" in desc or "papillon" in desc:                 return "papillon des gaz"
    elif "koer" in desc or "koeo" in desc or "idm" in desc or "dmh" in desc or "sbds" in desc or "egi" in desc: return "module de contrôle"
    elif "module de contrôle" in desc or "pcm" in desc or "ecu" in desc or "ecm" in desc or "tcm" in desc: return "module de contrôle"
    elif "module configuration" in desc or "incorrect module" in desc: return "module de contrôle"
    elif "rapport de boîte" in desc or "shift" in desc or "boîte" in desc or "gear" in desc or "overdrive" in desc: return "boîte de vitesses"
    elif "reverse engagement" in desc or "epc" in desc or "high charge neutral" in desc: return "boîte de vitesses"
    elif "transfer  case" in desc or "transfer case" in desc or "4x4" in desc: return "boîte de transfert"
    elif "input shaft" in desc or "inductive signature" in desc:   return "arbre de transmission"
    elif "convertisseur de couple" in desc or "torque" in desc:    return "convertisseur de couple"
    elif "immobilizer" in desc or "theft" in desc or "antivol" in desc or "transponder" in desc or "pats" in desc: return "système antivol"
    elif "keyless entry" in desc or "central lock" in desc or "double lock" in desc or "unlock" in desc or "lock condition" in desc: return "verrouillage centralisé"
    elif "psd not fully closed" in desc:                           return "porte coulissante"
    elif "alternator" in desc or "alternateur" in desc:            return "alternateur"
    elif "pedal" in desc or "pédale" in desc:                      return "pédale accélérateur"
    elif "boost" in desc or "turbo" in desc:                       return "turbocompresseur"
    elif "intake manifold" in desc or "imrc" in desc:              return "collecteur admission"
    elif "tension" in desc or "voltage" in desc or "vref" in desc: return "régulateur tension"
    elif "charging" in desc or ("charge" in desc and ("système" in desc or "external" in desc)): return "système de charge"
    elif "climatisation" in desc or "clim" in desc:                return "compresseur climatisation"
    elif "compressor" in desc or "compresseur" in desc:            return "compresseur"
    elif "audio" in desc or "radio" in desc:                       return "système audio"
    elif "tv module" in desc or "trafficmaster" in desc or "vics" in desc: return "multimédia"
    elif "gps" in desc or "gyroscope" in desc or "navigation" in desc or "compass" in desc: return "module navigation"
    elif "window" in desc or "fenêtre" in desc or "convertible top" in desc: return "lève-vitre / toit"
    elif "mirror" in desc or "rétroviseur" in desc:                return "rétroviseur"
    elif "steering" in desc or "direction" in desc or "psps" in desc: return "direction assistée"
    elif "heater" in desc or "chauffage" in desc:                  return "système de chauffage"
    elif "traction" in desc:                                       return "système traction"
    elif "stability" in desc:                                      return "système stabilité"
    elif "tire" in desc or "axle" in desc or "pneu" in desc:       return "pneu / essieu"
    elif "accélération" in desc or "accelerat" in desc:            return "accéléromètre"
    elif "octane" in desc or "elc système" in desc:                return "gestion moteur"
    elif "performance" in desc and "mode" in desc:                 return "module conduite"
    elif "calibration" in desc:                                    return "calibration système"
    elif "multi-faults" in desc:                                   return "multi-défauts"
    elif "antenna" in desc:                                        return "antenne"
    elif "gauge" in desc:                                          return "tableau de bord"
    elif "vanne" in desc:                                          return "vanne"
    elif "pompe" in desc:                                          return "pompe"
    elif "solénoïde" in desc:                                      return "solénoïde"
    elif "relais" in desc:                                         return "relais"
    elif "interrupteur" in desc:                                   return "interrupteur"
    elif "embrayage" in desc or "clutch" in desc:                  return "embrayage"
    elif "démarreur" in desc:                                      return "démarreur"
    elif "thermostat" in desc:                                     return "thermostat"
    elif "débit" in desc or "massique" in desc:                    return "débitmètre MAF"
    elif "pression" in desc or "collecteur" in desc:               return "capteur pression MAP"
    elif "température" in desc or "coolant" in desc or "refroidissement" in desc: return "sonde température"
    elif "carburant" in desc or "fuel" in desc:                    return "système carburant"
    elif "transmission" in desc or "vitesse" in desc:              return "capteur vitesse"
    elif "batterie" in desc or "battery" in desc or "alimentation" in desc: return "alimentation électrique"
    elif "abs" in desc or "frein" in desc or "brake" in desc:      return "système freinage"
    elif "air" in desc:                                            return "circuit air"
    elif "circuit" in desc:                                        return "composant électrique"
    elif "moteur" in desc or "engine" in desc:                     return "moteur"
    elif "lamp" in desc or "bulb" in desc:                         return "voyant"
    elif "scp" in desc or "j1850" in desc or "bus" in desc or "communication" in desc or "serial" in desc: return "bus communication"
    elif "seat" in desc or "siège" in desc:                        return "siège"
    elif "door" in desc or "porte" in desc:                        return "porte"
    elif "memory" in desc or "rom" in desc or "ram" in desc or "eeprom" in desc or "nvm" in desc or "code word" in desc: return "mémoire ECU"
    elif "phone" in desc or "cellular" in desc:                    return "téléphonie"
    elif "dc-dc" in desc or "converter" in desc:                   return "convertisseur DC-DC"
    elif "données" in desc or "data" in desc or "signal" in desc:  return "signal électronique"
    elif "driver side" in desc or "passenger side" in desc:        return "carrosserie"
    else:                                                          return "composant générique"

# ============================================================
# V9.4/V9.5 — GRAVITÉ AVEC DÉGRADÉ FAIBLE / MOYENNE / HAUTE
# (logique inchangée par rapport à V9.4, toujours valide)
# ============================================================

ESCALADE_HAUTE = {"temperature_moteur", "niveaux_vibration"}
ESCALADE_MOYENNE = {"qualite_huile", "consommation_carburant", "etat_batterie", "pression_pneus"}

def detect_gravite(code, sensors_of_code=None):
    if code.startswith("P03"):   base = "haute"
    elif code.startswith("C1"):  base = "haute"
    elif code.startswith("P05"): base = "moyenne"
    elif code.startswith("P01"): base = "moyenne"
    elif code.startswith("P02"): base = "haute"
    else:                        base = "faible"

    if not sensors_of_code:
        return base

    if sensors_of_code & ESCALADE_HAUTE:
        return "haute"

    if sensors_of_code & ESCALADE_MOYENNE:
        return "haute" if base == "haute" else "moyenne"

    return base

# ============================================================
# ASSIGNATION DYNAMIQUE DES DTC (basée capteurs hors seuil)
# ============================================================

SENSOR_DTC_KEYWORDS = {
    "temperature_moteur":     ["temperature", "coolant", "overheat", "thermostat", "cooling"],
    "qualite_huile":          ["oil", "huile", "lubrif"],
    "pression_pneus":         ["tire", "pneu", "tpms", "roue"],
    "etat_batterie":          ["battery", "batterie", "alternator", "alternateur", "charging system"],
    "consommation_carburant": ["fuel", "carburant", "injector", "injecteur", "trim", "mixture"],
    "niveaux_vibration":      ["misfire", "raté", "cylinder", "vibration", "balance"],
}

SENSOR_EXCLUDE_KEYWORDS = {
    "pression_pneus": ["climatisation", "clim", "pneumatic", "volant"],
    "etat_batterie":  ["court-circuit", "circuit court", "short circuit", "short to"],
}

SENSOR_STRONG_KEYWORDS = {
    "etat_batterie": [
        "alternator", "alternateur", "charging system", "batterie tension",
        "état batterie", "batterie faible", "state of charge",
        "batterie basse", "batterie lamp",
    ],
}

def build_dtc_pools(codes_df):
    pools = {sensor: [] for sensor in SENSOR_DTC_KEYWORDS}
    nb_exclus = {sensor: 0 for sensor in SENSOR_DTC_KEYWORDS}

    for _, row in codes_df.iterrows():
        code = str(safe_get(row, "Code", "")).strip()
        desc = str(safe_get(row, "Description", "")).lower()
        if not code:
            continue
        for sensor, keywords in SENSOR_DTC_KEYWORDS.items():
            if not any(kw in desc for kw in keywords):
                continue

            exclude_kws = SENSOR_EXCLUDE_KEYWORDS.get(sensor, [])
            strong_kws  = SENSOR_STRONG_KEYWORDS.get(sensor, [])

            if any(ex in desc for ex in exclude_kws) and not any(sk in desc for sk in strong_kws):
                nb_exclus[sensor] += 1
                continue

            pools[sensor].append(code)

    print("\n Filtrage — codes exclus (faux positifs détectés) :")
    for sensor, n in nb_exclus.items():
        if n:
            print(f"   ├─ {sensor:24s} : {n} codes exclus")

    generic_pool = [
        str(safe_get(row, "Code", "")).strip()
        for _, row in codes_df.iterrows()
        if str(safe_get(row, "Code", "")).startswith("P03")
    ]
    for sensor, pool in pools.items():
        if not pool:
            pools[sensor] = generic_pool or ["P0300"]
    return pools


def build_dtc_to_sensors(dtc_pools):
    dtc_to_sensors = {}
    for sensor, pool in dtc_pools.items():
        for code in pool:
            dtc_to_sensors.setdefault(code, set()).add(sensor)
    return dtc_to_sensors


def preview_dtc_pools(codes_df, dtc_pools, sample_size=10):
    desc_map = {
        str(safe_get(row, "Code", "")).strip(): safe_get(row, "Description", "")
        for _, row in codes_df.iterrows()
    }
    print("\n" + "=" * 70)
    print(" APERÇU DES POOLS DTC PAR CAPTEUR (V9.5)")
    print("=" * 70)
    for sensor, pool in dtc_pools.items():
        print(f"\n--- {sensor} ({len(pool)} codes) ---")
        for code in pool[:sample_size]:
            print(f"   {code:8s} : {desc_map.get(code, '')}")


DTC_MAP_FALLBACK = {
    "révision du moteur": {
        "bon":     ["P0300", "P0301", "P0302", "P0303", "P0304"],
        "moyen":   ["P0300", "P0301", "P0302", "P0506", "P0507"],
        "mauvais": ["P0300", "P0301", "P0302", "P0500", "P0501"],
    },
    "changement d'huile": {
        "bon":     ["P0506", "P0507", "P0500"],
        "moyen":   ["P0500", "P0501", "P0506"],
        "mauvais": ["P0500", "P0501", "P0300"],
    },
    "rotation des pneus": {
        "bon":     ["C1091", "C1095", "C1100"],
        "moyen":   ["C1091", "C1100", "C1200"],
        "mauvais": ["C1200", "C1201", "C1202"],
    },
}

PRIORITE_CAPTEURS = [
    "temperature_moteur", "qualite_huile", "consommation_carburant",
    "niveaux_vibration", "etat_batterie", "pression_pneus",
]

def assign_dtc(row, idx, dtc_pools, thresholds_actifs):
    anomalie = int(safe_get(row, "Anomalies_Détectées", 0))
    if anomalie == 0:
        return None

    valeurs_mesurees = {
        "qualite_huile":          safe_get(row, "Qualité_Huile", None),
        "temperature_moteur":     safe_get(row, "Température_Moteur", None),
        "pression_pneus":         safe_get(row, "Pression_Pneus", None),
        "consommation_carburant": safe_get(row, "Consommation_Carburant", None),
        "etat_batterie":          safe_get(row, "État_Batterie", None),
        "niveaux_vibration":      safe_get(row, "Niveaux_Vibration", None),
    }

    capteurs_hors_seuil = set()
    for (_, col_csv, v_min, v_max, v_critique, sens_critique) in thresholds_actifs:
        if col_csv not in valeurs_mesurees:
            continue
        valeur = valeurs_mesurees[col_csv]
        if valeur is None:
            continue
        if v_critique is not None:
            if sens_critique == "bas" and valeur <= v_critique:
                capteurs_hors_seuil.add(col_csv); continue
            if sens_critique == "haut" and valeur >= v_critique:
                capteurs_hors_seuil.add(col_csv); continue
        if v_max is not None and valeur > v_max:
            capteurs_hors_seuil.add(col_csv)
        elif v_min is not None and valeur < v_min:
            capteurs_hors_seuil.add(col_csv)

    vehicule_id = str(safe_get(row, "Identifiant_Véhicule", 0))
    hash_val = int(hashlib.md5(f"{vehicule_id}_{idx}".encode()).hexdigest(), 16)

    if capteurs_hors_seuil:
        sensor_choisi = next((s for s in PRIORITE_CAPTEURS if s in capteurs_hors_seuil),
                              next(iter(capteurs_hors_seuil)))
        candidates = dtc_pools.get(sensor_choisi) or ["P0300"]
        return candidates[hash_val % len(candidates)]

    type_entretien = str(safe_get(row, "Type_Entretien", "révision du moteur")).strip().lower()
    etat_freins = str(safe_get(row, "État_Freins", "bon")).strip().lower()
    type_key = next((k for k in DTC_MAP_FALLBACK if k in type_entretien), "révision du moteur")
    etat_key = etat_freins if etat_freins in DTC_MAP_FALLBACK[type_key] else "bon"
    candidates = DTC_MAP_FALLBACK[type_key][etat_key]
    return candidates[hash_val % len(candidates)]

# ============================================================
# CHARGEMENT DES CSV — chemins absolus
# ============================================================

CODES_ERREUR_PATH = r"E:\1er_projet_de_maitenance_predicitive\uploads\codes_erreur.csv"
MAINTENANCE_PATH   = r"E:\1er_projet_de_maitenance_predicitive\uploads\truckmind_dataset_complet.csv"

try:
    codes_df = pd.read_csv(CODES_ERREUR_PATH)
    print(f" codes_erreur.csv chargé — {len(codes_df)} codes.")
except Exception as e:
    print(" Erreur codes_erreur.csv :", e)
    codes_df = pd.DataFrame()

try:
    maintenance_df = pd.read_csv(MAINTENANCE_PATH)
    print(f" truckmind_dataset_complet.csv chargé — {len(maintenance_df)} lignes.")
except Exception as e:
    print(" Erreur truckmind_dataset_complet.csv :", e)
    maintenance_df = pd.DataFrame()

dtc_pools = build_dtc_pools(codes_df)
dtc_to_sensors = build_dtc_to_sensors(dtc_pools)

print(" Pools DTC par capteur (V9.5) :")
for sensor, pool in dtc_pools.items():
    print(f"   ├─ {sensor:24s} : {len(pool)} codes candidats")

preview_dtc_pools(codes_df, dtc_pools, sample_size=10)

# ============================================================
# REMPLISSAGE : TABLE knowledge
# ============================================================

for _, row in codes_df.iterrows():
    dtc         = safe_get(row, "Code", "UNKNOWN")
    description = safe_get(row, "Description", "Aucune description")
    systeme     = detect_system(description)
    piece       = detect_piece(description)
    gravite     = detect_gravite(str(dtc), dtc_to_sensors.get(str(dtc).strip()))
    cursor.execute("""
    INSERT OR REPLACE INTO knowledge (dtc, symptome, systeme, piece, gravite)
    VALUES (?, ?, ?, ?, ?)
    """, (dtc, description, systeme, piece, gravite))

print(f" Table knowledge remplie — {len(codes_df)} codes OBD insérés.")

# ============================================================
# PASSE 1 — tables de référence (vehicules / chauffeurs / employes / routes)
# ============================================================

nb_vehicules = 0
for _, row in maintenance_df.iterrows():
    vehicule_id = safe_get(row, "Identifiant_Véhicule", "UNKNOWN")
    cursor.execute("""
    INSERT OR IGNORE INTO vehicules
        (vehicule_id, annee_fabrication, heures_utilisation, capacite_charge_t,
         categorie_age, facteur_age, valeur_achat_mad, valeur_actuelle_mad)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        vehicule_id,
        safe_get(row, "Année_Fabrication", None),
        safe_get(row, "Heures_Utilisation", None),
        safe_get(row, "Capacité_Charge", None),
        safe_get(row, "Categorie_Age", None),
        safe_get(row, "Facteur_Age", None),
        safe_get(row, "Valeur_Achat_MAD", None),
        safe_get(row, "Valeur_Actuelle_MAD", None),
    ))
    nb_vehicules += cursor.rowcount

print(f" Table vehicules remplie — {nb_vehicules} véhicules insérés.")

nb_chauffeurs = 0
for _, row in maintenance_df.iterrows():
    chauffeur_id = safe_get(row, "Chauffeur_ID", None)
    if chauffeur_id is None:
        continue
    cursor.execute("""
    INSERT OR IGNORE INTO chauffeurs
        (chauffeur_id, nom, experience_annees, permis_numero, permis_categorie,
         permis_date_expiration, salaire_base_mensuel_mad, prime_activite_mad)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        chauffeur_id,
        safe_get(row, "Chauffeur_Nom", None),
        safe_get(row, "Chauffeur_Experience_Annees", None),
        safe_get(row, "Permis_Numero", None),
        safe_get(row, "Permis_Categorie", None),
        safe_get(row, "Permis_Date_Expiration", None),
        safe_get(row, "Salaire_Base_Mensuel_MAD", None),
        safe_get(row, "Prime_Activite_MAD", None),
    ))
    nb_chauffeurs += cursor.rowcount

print(f" Table chauffeurs remplie — {nb_chauffeurs} chauffeurs insérés.")

nb_employes = 0
for _, row in maintenance_df.iterrows():
    employe_id = safe_get(row, "Employe_ID", None)
    if employe_id is None:
        continue
    cursor.execute("""
    INSERT OR IGNORE INTO employes (employe_id, nom, departement, poste)
    VALUES (?, ?, ?, ?)
    """, (
        employe_id,
        safe_get(row, "Employe_Nom", None),
        safe_get(row, "Departement", None),
        safe_get(row, "Poste", None),
    ))
    nb_employes += cursor.rowcount

print(f" Table employes remplie — {nb_employes} employés Finance/Logistique insérés.")

nb_routes = 0
for _, row in maintenance_df.iterrows():
    route_nom = safe_get(row, "Route_Nom", None)
    if route_nom is None:
        continue
    cursor.execute("""
    INSERT OR IGNORE INTO routes (route_nom, distance_km, duree_estimee_h, type_itineraire)
    VALUES (?, ?, ?, ?)
    """, (
        route_nom,
        safe_get(row, "Route_Distance_Km", None),
        safe_get(row, "Route_Duree_Estimee_H", None),
        safe_get(row, "Info_Itinéraire", None),
    ))
    nb_routes += cursor.rowcount

conn.commit()
print(f" Table routes remplie — {nb_routes} routes insérées.")

cursor.execute("SELECT route_id, route_nom FROM routes")
route_id_map = {nom: rid for rid, nom in cursor.fetchall()}

# ============================================================
# PASSE 2 — maintenance + maintenance_alerts + trips + fleet_costs
# ============================================================

cursor.execute("""
    SELECT id, colonne_csv, valeur_min, valeur_max, valeur_critique, sens_critique
    FROM thresholds
    WHERE colonne_csv IS NOT NULL
      AND niveau_alerte != 'NORMAL'
""")
thresholds_actifs = cursor.fetchall()

nb_avec_dtc = 0
nb_sans_dtc = 0
nb_alerts   = 0
nb_trips    = 0
nb_costs    = 0

for idx, row in maintenance_df.iterrows():
    vehicule_id            = safe_get(row, "Identifiant_Véhicule", "UNKNOWN")
    date                   = safe_get(row, "Date_Dernier_Entretien", "2024-01-01")
    action                 = safe_get(row, "Type_Entretien", "maintenance générale")
    etat_freins            = safe_get(row, "État_Freins", "inconnu")
    qualite_huile          = safe_get(row, "Qualité_Huile", None)
    anomalie_detectee      = safe_get(row, "Anomalies_Détectées", 0)
    entretien_necessaire   = safe_get(row, "Entretien_Nécessaire", 0)
    score_predictif        = safe_get(row, "Score_Prédictif", 0)
    niveau_risque          = safe_get(row, "Niveau_Risque", None)
    historique_pannes      = safe_get(row, "Historique_Pannes", None)
    temperature_moteur     = safe_get(row, "Température_Moteur", None)
    pression_pneus         = safe_get(row, "Pression_Pneus", None)
    consommation_carburant = safe_get(row, "Consommation_Carburant", None)
    etat_batterie          = safe_get(row, "État_Batterie", None)
    niveaux_vibration      = safe_get(row, "Niveaux_Vibration", None)

    dtc = assign_dtc(row, idx, dtc_pools, thresholds_actifs)
    if dtc: nb_avec_dtc += 1
    else:   nb_sans_dtc += 1

    cursor.execute("""
    INSERT INTO maintenance
    (vehicule_id, dtc, date, action, etat_freins, qualite_huile,
     anomalie_detectee, entretien_necessaire, score_predictif,
     niveau_risque, historique_pannes,
     temperature_moteur, pression_pneus, consommation_carburant,
     etat_batterie, niveaux_vibration)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicule_id, dtc, date, action, etat_freins,
          qualite_huile, anomalie_detectee, entretien_necessaire,
          score_predictif, niveau_risque, historique_pannes,
          temperature_moteur, pression_pneus,
          consommation_carburant, etat_batterie, niveaux_vibration))

    maintenance_id = cursor.lastrowid

    valeurs_mesurees = {
        "qualite_huile":          qualite_huile,
        "score_predictif":        score_predictif,
        "temperature_moteur":     temperature_moteur,
        "pression_pneus":         pression_pneus,
        "consommation_carburant": consommation_carburant,
        "etat_batterie":          etat_batterie,
        "niveaux_vibration":      niveaux_vibration,
    }

    for (t_id, col_csv, v_min, v_max, v_critique, sens_critique) in thresholds_actifs:
        if col_csv not in valeurs_mesurees:
            continue
        valeur = valeurs_mesurees[col_csv]
        if valeur is None:
            continue

        depassement = None

        if v_critique is not None:
            if sens_critique == "bas" and valeur <= v_critique:
                depassement = "CRITIQUE"
            elif sens_critique == "haut" and valeur >= v_critique:
                depassement = "CRITIQUE"

        if depassement is None and v_max is not None and valeur > v_max:
            depassement = "MAX"
        if depassement is None and v_min is not None and valeur < v_min:
            depassement = "MIN"

        if depassement:
            cursor.execute("""
            INSERT INTO maintenance_alerts
                (maintenance_id, threshold_id, valeur_mesuree, depassement)
            VALUES (?, ?, ?, ?)
            """, (maintenance_id, t_id, valeur, depassement))
            nb_alerts += 1

    chauffeur_id      = safe_get(row, "Chauffeur_ID", None)
    employe_id        = safe_get(row, "Employe_ID", None)
    trajet_id_externe = safe_get(row, "Trajet_ID", None)
    route_nom         = safe_get(row, "Route_Nom", None)
    route_id          = route_id_map.get(route_nom) if route_nom else None

    cursor.execute("""
    INSERT INTO trips
        (trajet_id_externe, vehicule_id, chauffeur_id, employe_id, route_id, date,
         charge_reelle_t, type_marchandise, facteur_marchandise, marchandise_dangereuse,
         conditions_meteo, conditions_route, delais_livraison_h,
         distance_estimee_km, carburant_estime_litres, cout_carburant_mad,
         revenu_estime_mad, impact_efficacite)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trajet_id_externe, vehicule_id, chauffeur_id, employe_id, route_id, date,
        safe_get(row, "Charge_Réelle", None),
        safe_get(row, "Type_Marchandise", None),
        safe_get(row, "Facteur_Marchandise", None),
        int(bool(safe_get(row, "Marchandise_Dangereuse", False))),
        safe_get(row, "Conditions_Météo", None),
        safe_get(row, "Conditions_Route", None),
        safe_get(row, "Délais_Livraison", None),
        safe_get(row, "Distance_Totale_Estimee_Km", None),
        safe_get(row, "Carburant_Total_Estime_Litres", None),
        safe_get(row, "Cout_Carburant_Total_MAD", None),
        safe_get(row, "Revenu_Total_Estime_MAD", None),
        safe_get(row, "Impact_Efficacité", None),
    ))
    nb_trips += 1

    cursor.execute("""
    INSERT INTO fleet_costs
        (vehicule_id, cout_entretien_mad, cout_carburant_total_mad,
         valeur_achat_mad, valeur_actuelle_mad, rentabilite_nette_mad,
         temps_arret_entretien_h)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        vehicule_id,
        safe_get(row, "Coût_Entretien", None),
        safe_get(row, "Cout_Carburant_Total_MAD", None),
        safe_get(row, "Valeur_Achat_MAD", None),
        safe_get(row, "Valeur_Actuelle_MAD", None),
        safe_get(row, "Rentabilite_Nette_MAD", None),
        safe_get(row, "Temps_Arrêt_Entretien", None),
    ))
    nb_costs += 1

print(f" Table maintenance remplie :")
print(f"   ├─ {nb_avec_dtc} enregistrements AVEC DTC")
print(f"   └─ {nb_sans_dtc} enregistrements SANS DTC")
print(f" Table maintenance_alerts : {nb_alerts} alertes générées (NORMAL exclu).")
print(f" Table trips : {nb_trips} trajets insérés (avec trajet_id_externe et employe_id).")
print(f" Table fleet_costs : {nb_costs} enregistrements de coûts insérés.")

conn.commit()
print(" Données sauvegardées.")

# ============================================================
# VÉRIFICATIONS & STATISTIQUES
# ============================================================

print("\n" + "="*60)
print(" VÉRIFICATIONS DES RELATIONS")
print("="*60)

df_check = pd.read_sql_query("""
    SELECT m.vehicule_id, m.dtc, m.action, m.etat_freins,
           k.symptome, k.systeme, k.gravite
    FROM maintenance m
    JOIN knowledge k ON m.dtc = k.dtc
    LIMIT 5
""", conn)
print(df_check.to_string())

df_alerts = pd.read_sql_query("""
    SELECT m.vehicule_id, m.date,
           t.parametre, t.unite, t.niveau_alerte, t.lampe,
           ma.valeur_mesuree, ma.depassement,
           t.action AS action_recommandee
    FROM maintenance_alerts ma
    JOIN maintenance  m ON ma.maintenance_id = m.id
    JOIN thresholds   t ON ma.threshold_id   = t.id
    ORDER BY ma.id
    LIMIT 5
""", conn)
print(df_alerts.to_string())

print("\n JOIN trips ↔ vehicules ↔ chauffeurs ↔ employes ↔ routes (5 premiers) :")
df_trips = pd.read_sql_query("""
    SELECT tr.trajet_id_externe, tr.vehicule_id, v.categorie_age,
           c.nom AS chauffeur, e.nom AS responsable_logistique, e.departement,
           r.route_nom, r.type_itineraire, tr.type_marchandise,
           tr.revenu_estime_mad
    FROM trips tr
    JOIN vehicules  v ON tr.vehicule_id  = v.vehicule_id
    LEFT JOIN chauffeurs c ON tr.chauffeur_id = c.chauffeur_id
    LEFT JOIN employes   e ON tr.employe_id   = e.employe_id
    LEFT JOIN routes     r ON tr.route_id     = r.route_id
    LIMIT 5
""", conn)
print(df_trips.to_string())

print("\n JOIN fleet_costs ↔ vehicules (TOP 5 rentabilité) :")
df_costs = pd.read_sql_query("""
    SELECT fc.vehicule_id, v.categorie_age,
           fc.cout_entretien_mad, fc.cout_carburant_total_mad,
           fc.rentabilite_nette_mad
    FROM fleet_costs fc
    JOIN vehicules v ON fc.vehicule_id = v.vehicule_id
    ORDER BY fc.rentabilite_nette_mad DESC
    LIMIT 5
""", conn)
print(df_costs.to_string())

df_stats_alerts = pd.read_sql_query("""
    SELECT t.parametre, t.niveau_alerte, t.lampe,
           COUNT(*) AS nb_alertes
    FROM maintenance_alerts ma
    JOIN thresholds t ON ma.threshold_id = t.id
    GROUP BY t.parametre, t.niveau_alerte
    ORDER BY nb_alertes DESC
    LIMIT 10
""", conn)
print(df_stats_alerts.to_string())

df_dtc_stats = pd.read_sql_query("""
    SELECT m.action AS type_entretien, m.dtc,
           COUNT(*) AS nb_occurrences, k.gravite
    FROM maintenance m
    JOIN knowledge k ON m.dtc = k.dtc
    GROUP BY m.dtc
    ORDER BY nb_occurrences DESC
    LIMIT 10
""", conn)
print(df_dtc_stats.to_string())

df_gravite_stats = pd.read_sql_query("""
    SELECT gravite, COUNT(*) AS nb_codes
    FROM knowledge
    GROUP BY gravite
    ORDER BY nb_codes DESC
""", conn)
print("\n Répartition des gravités dans knowledge (V9.5) :")
print(df_gravite_stats.to_string())

# ============================================================
# FONCTIONS DE REQUÊTE
# ============================================================

def query_dtc(code):
    print(f"\n Recherche DTC : {code}")
    print("=" * 40)
    cursor.execute("SELECT * FROM knowledge WHERE dtc = ?", (code,))
    k = cursor.fetchone()
    if k:
        print(" DIAGNOSTIC")
        print(f"  DTC      : {k[0]}")
        print(f"  Symptôme : {k[1]}")
        print(f"  Système  : {k[2]}")
        print(f"  Pièce    : {k[3]}")
        print(f"  Gravité  : {k[4]}")
    else:
        print(" Aucun diagnostic trouvé.")


def query_vehicle_full(vehicule_id):
    print(f"\n Fiche complète véhicule : {vehicule_id}")
    print("=" * 60)

    v = pd.read_sql_query("SELECT * FROM vehicules WHERE vehicule_id = ?", conn, params=(vehicule_id,))
    if v.empty:
        print(" Véhicule introuvable.")
        return
    print(" INFOS VÉHICULE :")
    print(v.to_string(index=False))

    m = pd.read_sql_query("""
        SELECT date, action, dtc, score_predictif, niveau_risque,
               historique_pannes, temperature_moteur, pression_pneus
        FROM maintenance WHERE vehicule_id = ? ORDER BY date DESC
    """, conn, params=(vehicule_id,))
    print(f"\n MAINTENANCE ({len(m)}) :")
    print(m.to_string(index=False))

    al = pd.read_sql_query("""
        SELECT t.parametre, t.niveau_alerte, ma.valeur_mesuree, ma.depassement
        FROM maintenance_alerts ma
        JOIN maintenance m ON ma.maintenance_id = m.id
        JOIN thresholds  t ON ma.threshold_id   = t.id
        WHERE m.vehicule_id = ?
    """, conn, params=(vehicule_id,))
    print(f"\n ALERTES ({len(al)}) :")
    print(al.to_string(index=False))

    t = pd.read_sql_query("""
        SELECT tr.trajet_id_externe, tr.date, c.nom AS chauffeur,
               e.nom AS responsable_logistique, r.route_nom, tr.type_marchandise,
               tr.revenu_estime_mad, tr.cout_carburant_mad
        FROM trips tr
        LEFT JOIN chauffeurs c ON tr.chauffeur_id = c.chauffeur_id
        LEFT JOIN employes   e ON tr.employe_id   = e.employe_id
        LEFT JOIN routes     r ON tr.route_id     = r.route_id
        WHERE tr.vehicule_id = ?
    """, conn, params=(vehicule_id,))
    print(f"\n TRAJETS ({len(t)}) :")
    print(t.to_string(index=False))

    fc = pd.read_sql_query("SELECT * FROM fleet_costs WHERE vehicule_id = ?", conn, params=(vehicule_id,))
    print(f"\n COÛTS & RENTABILITÉ :")
    print(fc.to_string(index=False))


def query_thresholds(parametre=None):
    print(f"\n Seuils techniques {'— ' + parametre if parametre else '(tous)'}")
    print("=" * 60)
    if parametre:
        df = pd.read_sql_query("""
            SELECT parametre, valeur_min, valeur_max, valeur_critique, sens_critique,
                   unite, lampe, niveau_alerte, action, source
            FROM thresholds WHERE parametre LIKE ?
        """, conn, params=(f"%{parametre}%",))
    else:
        df = pd.read_sql_query("""
            SELECT parametre, valeur_min, valeur_max, valeur_critique, sens_critique,
                   unite, lampe, niveau_alerte, action, source
            FROM thresholds
        """, conn)
    print(df.to_string())


def get_fleet_stats_header():
    cursor.execute("""
        SELECT
            AVG(score_predictif), MIN(score_predictif), MAX(score_predictif),
            SUM(CASE WHEN score_predictif > 0.8 THEN 1 ELSE 0 END),
            COUNT(*),
            SUM(anomalie_detectee), SUM(entretien_necessaire),
            AVG(qualite_huile), MIN(qualite_huile), MAX(qualite_huile),
            AVG(temperature_moteur), MIN(temperature_moteur), MAX(temperature_moteur),
            AVG(pression_pneus), MIN(pression_pneus), MAX(pression_pneus)
        FROM maintenance
    """)
    row = cursor.fetchone()
    s = [0 if v is None else v for v in row]

    cursor.execute("""
        SELECT t.niveau_alerte, COUNT(*) AS nb
        FROM maintenance_alerts ma
        JOIN thresholds t ON ma.threshold_id = t.id
        GROUP BY t.niveau_alerte
    """)
    alert_counts = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT SUM(rentabilite_nette_mad), AVG(rentabilite_nette_mad) FROM fleet_costs")
    rent_sum, rent_avg = cursor.fetchone()
    rent_sum = rent_sum or 0
    rent_avg = rent_avg or 0

    header = f"""
### FLEET_STATS — Statistiques globales (base complète : {s[4]} enregistrements)
    ÉCHELLE score_predictif : 0.0 = faible risque → 1.0 = risque critique
  • Score prédictif   : Moyenne={s[0]:.3f} | Min={s[1]:.3f} | Max={s[2]:.3f} | Critiques (>0.8): {s[3]} ({100*s[3]/s[4] if s[4] else 0:.1f}%)
  • Anomalies         : {s[5]}/{s[4]} ({100*s[5]/s[4] if s[4] else 0:.1f}%)
  • Entretien nécess. : {s[6]}/{s[4]} ({100*s[6]/s[4] if s[4] else 0:.1f}%)
  • Qualité huile     : Moyenne={s[7]:.1f}% | Min={s[8]:.1f}% | Max={s[9]:.1f}%
  • Température moteur: Moyenne={s[10]:.1f}°C | Min={s[11]:.1f}°C | Max={s[12]:.1f}°C
  • Pression pneus    : Moyenne={s[13]:.1f} PSI | Min={s[14]:.1f} PSI | Max={s[15]:.1f} PSI

### SEUILS_ALERTES_FLEET (via table thresholds)
  • ARRÊT IMMÉDIAT : {alert_counts.get('ARRÊT IMMÉDIAT', 0)} alertes
  • SURVEILLANCE   : {alert_counts.get('SURVEILLANCE', 0)} alertes
  • Total alertes  : {sum(alert_counts.values())} sur {s[4]} enregistrements

### FINANCE_FLEET (via table fleet_costs)
  • Rentabilité nette totale : {rent_sum:,.0f} MAD
  • Rentabilité nette moyenne/véhicule : {rent_avg:,.0f} MAD
"""
    return header


# ============================================================
# TESTS
# ============================================================

print("\n" + "="*60)
print(" TESTS DES FONCTIONS")
print("="*60)

query_dtc("P0301")
query_dtc("P0483")
query_dtc("P1799")
query_vehicle_full("V0001")
query_thresholds("Pression Pneus")
query_thresholds("Qualité Huile")
query_thresholds("État Batterie")

print("\n  FLEET STATS HEADER :")
print(get_fleet_stats_header())

conn.close()
print("\n  Connexion SQLite fermée.")