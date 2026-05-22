# ============================================================
# Projet : AI Truck Diagnostic Database — VERSION 5
# Corrections :
#   1. Suppression du doublon thresholds (INSERT OR IGNORE)
#   2. Pression pneus corrigée en PSI (94–131 PSI réels CSV)
# Auteure : AFFAKI Aya — EST Tétouan
# ============================================================

import pandas as pd
import sqlite3
import os
import hashlib

# --- Connexion à la base de données SQLite ---
db_dir = r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\test\knowledge"
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, "truck_diagnostic.db")

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
cursor = conn.cursor()
print(f"✅ Base de données connectée à : {db_path}")

# ============================================================
# CRÉATION DES TABLES
# ============================================================

# ── Table 1 : knowledge (codes DTC) ────────────────────────
cursor.execute("""
CREATE TABLE IF NOT EXISTS knowledge (
    dtc      TEXT PRIMARY KEY,
    symptome TEXT,
    systeme  TEXT,
    piece    TEXT,
    gravite  TEXT
)
""")

# ── Table 2 : thresholds ─────────────────────────────────────
# FIX #1 : ajout de UNIQUE(parametre, niveau_alerte) pour éviter
#          les doublons lors de relances successives du script
cursor.execute("""
CREATE TABLE IF NOT EXISTS thresholds (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parametre        TEXT NOT NULL,
    colonne_csv      TEXT,
    valeur_min       REAL,
    valeur_max       REAL,
    valeur_critique  REAL,
    unite            TEXT,
    lampe            TEXT,
    niveau_alerte    TEXT,
    action           TEXT,
    source           TEXT,
    UNIQUE(parametre, niveau_alerte)   -- ← empêche les doublons
)
""")

# ── Table 3 : maintenance ────────────────────────────────────
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
    temperature_moteur     REAL,
    pression_pneus         REAL,
    consommation_carburant REAL,
    etat_batterie          REAL,
    niveaux_vibration      REAL,
    FOREIGN KEY (dtc) REFERENCES knowledge(dtc)
)
""")

# ── Table 4 : maintenance_alerts ─────────────────────────────
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

print("✅ 4 tables créées avec relations FK.")

# ============================================================
# REMPLISSAGE DE LA TABLE thresholds
# FIX #2 : Pression pneus en PSI (données CSV : min=94, max=131)
#          Seuils Volvo FH/FM poids-lourd :
#            Normale   : 100–120 PSI
#            Basse     : < 90 PSI  → JAUNE
#            Critique  : < 75 PSI  → ROUGE
#            Haute     : > 125 PSI → ROUGE (risque éclatement)
# ============================================================

thresholds_data = [
    # ── Température moteur ──────────────────────────────────────────────
    ("Température Moteur",       "temperature_moteur",    None,  100.0,  None,   "°C",    "JAUNE", "SURVEILLANCE",    "Surveiller — risque de surchauffe",                   "Manuel Volvo FH/FM p.5"),
    ("Température Moteur",       "temperature_moteur",    None,  105.0,  None,   "°C",    "ROUGE", "ARRÊT IMMÉDIAT",  "Arrêter le moteur immédiatement — refroidir 10-15 min", "Manuel Volvo FH/FM p.24"),

    # ── Pression pneus (PSI) — FIX #2 ──────────────────────────────────
    ("Pression Pneus",           "pression_pneus",        100.0, 120.0,  None,   "PSI",   "VERT",    "NORMAL",          "Pression dans la plage normale (100–120 PSI)",         "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",           "pression_pneus",         90.0,  None,  None,   "PSI",   "JAUNE", "SURVEILLANCE",    "Pression basse — vérifier les pneus avant départ",     "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",           "pression_pneus",         None,  None,   75.0,  "PSI",   "ROUGE", "ARRÊT IMMÉDIAT",  "Pression critique — risque d'éclatement",               "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus Haute",     "pression_pneus",         None,  125.0,  None,  "PSI",   "ROUGE", "ARRÊT IMMÉDIAT",  "Surpression — risque d'éclatement à chaud",             "Norme poids-lourd Volvo FH/FM"),

    # ── Qualité huile ────────────────────────────────────────────────────
    ("Qualité Huile",            "qualite_huile",          40.0,  None,   None,  "%",     "JAUNE", "SURVEILLANCE",    "Huile dégradée — planifier vidange sous 30 jours",     "Manuel Volvo FH/FM p.1"),
    ("Qualité Huile",            "qualite_huile",          None,  None,   20.0,  "%",     "ROUGE", "ARRÊT IMMÉDIAT",  "Huile très dégradée — vidange immédiate obligatoire",   "Manuel Volvo FH/FM p.1"),

    # ── État batterie ────────────────────────────────────────────────────
    ("État Batterie",            "etat_batterie",          30.0,  None,   None,  "%",     "JAUNE", "SURVEILLANCE",    "Batterie faible — vérifier l'alternateur",              "Manuel Volvo FH/FM p.84"),
    ("État Batterie",            "etat_batterie",          None,  None,   15.0,  "%",     "ROUGE", "ARRÊT IMMÉDIAT",  "Batterie critique — risque de panne démarrage",          "Manuel Volvo FH/FM p.84"),

    # ── Consommation carburant ───────────────────────────────────────────
    ("Consommation Carburant",   "consommation_carburant", None,  35.0,   None,  "L/100km","JAUNE","SURVEILLANCE",    "Consommation anormale — vérifier injection/filtre",    "Manuel Volvo FH/FM p.1"),
    ("Consommation Carburant",   "consommation_carburant", None,  None,   45.0,  "L/100km","ROUGE","ARRÊT IMMÉDIAT",  "Consommation critique — diagnostic immédiat requis",    "Manuel Volvo FH/FM p.1"),

    # ── Niveaux vibration ────────────────────────────────────────────────
    ("Niveaux Vibration",        "niveaux_vibration",      None,   8.0,   None,  "mm/s",  "JAUNE", "SURVEILLANCE",    "Vibrations anormales — vérifier roues et suspension",  "Diagnostic standard Volvo"),
    ("Niveaux Vibration",        "niveaux_vibration",      None,   None,  12.0,  "mm/s",  "ROUGE", "ARRÊT IMMÉDIAT",  "Vibrations critiques — risque de défaillance",          "Diagnostic standard Volvo"),

    # ── Score prédictif ──────────────────────────────────────────────────
    ("Score Prédictif",          "score_predictif",        None,   0.5,   None,  "score", "JAUNE", "SURVEILLANCE",    "Risque modéré — planifier entretien sous 15 jours",    "Modèle prédictif TruckMind"),
    ("Score Prédictif",          "score_predictif",        None,   None,   0.8,  "score", "ROUGE", "ARRÊT IMMÉDIAT",  "Risque critique — entretien immédiat obligatoire",      "Modèle prédictif TruckMind"),

    # ── TCS ──────────────────────────────────────────────────────────────
    ("Vitesse TCS",              None,                     None,  40.0,   None,  "km/h",  "VERT",    "NORMAL",
     "TCS actif comme frein différentiel automatique à vitesse < 40 km/h",
     "Manuel Volvo FH/FM p.32 (TCS)"),

    # ── Frein de stationnement ───────────────────────────────────────────
    ("Pression Frein Stationnement", None,                  5.0,  None,   None,  "bar",   "ROUGE", "ARRÊT IMMÉDIAT",
     "Pression insuffisante — appuyer valve verrouillage pour désengager",
     "Manuel Volvo FH/FM p.33"),

    # ── Intervalle vidange ───────────────────────────────────────────────
    ("Intervalle Vidange Huile (km)",  None,                None, None, 30000.0, "km",    "JAUNE", "SURVEILLANCE",
     "Vidange obligatoire tous les 30 000 km OU 12 mois — la première échéance prime",
     "Manuel Volvo FH/FM p.1 (DUAL CONDITIONS)"),
    ("Intervalle Vidange Huile (mois)", None,               None, None,   12.0,  "mois",  "JAUNE", "SURVEILLANCE",
     "Vidange obligatoire tous les 12 mois OU 30 000 km — la première échéance prime",
     "Manuel Volvo FH/FM p.1 (DUAL CONDITIONS)"),

    # ── Température réfrigérant ──────────────────────────────────────────
    ("Température Réfrigérant Démarrage", None,             50.0, None,   None,  "°C",    "JAUNE", "SURVEILLANCE",
     "Attendre que le réfrigérant soit > 50°C avant de solliciter le moteur",
     "Manuel Volvo FH/FM p.24"),

    # ── Régime ralenti ───────────────────────────────────────────────────
    ("Régime Ralenti",           None,                     550.0, 650.0,  None,  "tr/min", "VERT",   "NORMAL",
     "Régime de ralenti normal entre 550 et 650 tr/min",
     "Manuel Volvo FH/FM p.25"),
]

# FIX #1 : INSERT OR IGNORE évite les doublons si le script est relancé
cursor.executemany("""
INSERT OR IGNORE INTO thresholds
    (parametre, colonne_csv, valeur_min, valeur_max, valeur_critique,
     unite, lampe, niveau_alerte, action, source)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", thresholds_data)

nb_thresholds = cursor.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0]
print(f"✅ Table thresholds : {nb_thresholds} seuils techniques (sans doublons).")

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

def detect_gravite(code):
    if code.startswith("P03"):   return "haute"
    elif code.startswith("C1"):  return "haute"
    elif code.startswith("P05"): return "moyenne"
    elif code.startswith("P01"): return "moyenne"
    elif code.startswith("P02"): return "haute"
    else:                        return "faible"

# ── DTC mapping ─────────────────────────────────────────────
DTC_MAP = {
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

def assign_dtc(row, idx):
    anomalie = int(safe_get(row, "Anomalies_Détectées", 0))
    if anomalie == 0:
        return None
    type_entretien = str(safe_get(row, "Type_Entretien", "révision du moteur")).strip().lower()
    etat_freins    = str(safe_get(row, "État_Freins", "bon")).strip().lower()
    type_key = None
    for k in DTC_MAP:
        if k in type_entretien:
            type_key = k
            break
    if type_key is None:
        type_key = "révision du moteur"
    etat_key   = etat_freins if etat_freins in DTC_MAP[type_key] else "bon"
    candidates = DTC_MAP[type_key][etat_key]
    vehicule_id = str(safe_get(row, "Identifiant_Véhicule", 0))
    hash_val    = int(hashlib.md5(f"{vehicule_id}_{idx}".encode()).hexdigest(), 16)
    return candidates[hash_val % len(candidates)]

# ============================================================
# CHARGEMENT DES CSV
# ============================================================

try:
    codes_df = pd.read_csv(r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\uploads_sans_clean\codes_erreur.csv")
    print(f"✅ codes_erreur.csv chargé — {len(codes_df)} codes.")
except Exception as e:
    print("❌ Erreur codes_erreur.csv :", e)
    codes_df = pd.DataFrame()

try:
    maintenance_df = pd.read_csv(r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\uploads_sans_clean\histoire_de_maintenance.csv")
    print(f"✅ histoire_de_maintenance.csv chargé — {len(maintenance_df)} lignes.")
except Exception as e:
    print("❌ Erreur histoire_de_maintenance.csv :", e)
    maintenance_df = pd.DataFrame()

# ============================================================
# REMPLISSAGE : TABLE knowledge
# ============================================================

for _, row in codes_df.iterrows():
    dtc         = safe_get(row, "Code", "UNKNOWN")
    description = safe_get(row, "Description", "Aucune description")
    systeme     = detect_system(description)
    piece       = detect_piece(description)
    gravite     = detect_gravite(str(dtc))
    cursor.execute("""
    INSERT OR REPLACE INTO knowledge (dtc, symptome, systeme, piece, gravite)
    VALUES (?, ?, ?, ?, ?)
    """, (dtc, description, systeme, piece, gravite))

print(f"✅ Table knowledge remplie — {len(codes_df)} codes OBD insérés.")

# ============================================================
# REMPLISSAGE : TABLE maintenance + maintenance_alerts
# ============================================================

# Pré-charger les thresholds actifs
cursor.execute("SELECT id, colonne_csv, valeur_min, valeur_max, valeur_critique FROM thresholds WHERE colonne_csv IS NOT NULL")
thresholds_actifs = cursor.fetchall()

nb_avec_dtc = 0
nb_sans_dtc = 0
nb_alerts   = 0
maintenance_clean_rows = []

for idx, row in maintenance_df.iterrows():
    vehicule_id            = safe_get(row, "Identifiant_Véhicule", "UNKNOWN")
    date                   = safe_get(row, "Date_Dernier_Entretien", "2024-01-01")
    action                 = safe_get(row, "Type_Entretien", "maintenance générale")
    etat_freins            = safe_get(row, "État_Freins", "inconnu")
    qualite_huile          = safe_get(row, "Qualité_Huile", None)
    anomalie_detectee      = safe_get(row, "Anomalies_Détectées", 0)
    entretien_necessaire   = safe_get(row, "Entretien_Nécessaire", 0)
    score_predictif        = safe_get(row, "Score_Prédictif", 0)
    temperature_moteur     = safe_get(row, "Température_Moteur", None)
    pression_pneus         = safe_get(row, "Pression_Pneus", None)
    consommation_carburant = safe_get(row, "Consommation_Carburant", None)
    etat_batterie          = safe_get(row, "État_Batterie", None)
    niveaux_vibration      = safe_get(row, "Niveaux_Vibration", None)

    dtc = assign_dtc(row, idx)
    if dtc: nb_avec_dtc += 1
    else:   nb_sans_dtc += 1

    cursor.execute("""
    INSERT INTO maintenance
    (vehicule_id, dtc, date, action, etat_freins, qualite_huile,
     anomalie_detectee, entretien_necessaire, score_predictif,
     temperature_moteur, pression_pneus, consommation_carburant,
     etat_batterie, niveaux_vibration)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (vehicule_id, dtc, date, action, etat_freins,
          qualite_huile, anomalie_detectee, entretien_necessaire,
          score_predictif, temperature_moteur, pression_pneus,
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

    for (t_id, col_csv, v_min, v_max, v_critique) in thresholds_actifs:
        if col_csv not in valeurs_mesurees:
            continue
        valeur = valeurs_mesurees[col_csv]
        if valeur is None:
            continue

        depassement = None
        if v_critique is not None:
            if v_min is None and valeur >= v_critique:
                depassement = "CRITIQUE"
            elif v_max is None and v_min is not None and valeur <= v_critique:
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

    maintenance_clean_rows.append({
        "Identifiant_Véhicule":     vehicule_id,
        "DTC_assigne":              dtc if dtc else "",
        "Date_Dernier_Entretien":   date,
        "Type_Entretien":           action,
        "État_Freins":              etat_freins,
        "Qualité_Huile":            qualite_huile,
        "Anomalies_Détectées":      anomalie_detectee,
        "Entretien_Nécessaire":     entretien_necessaire,
        "Score_Prédictif":          score_predictif,
        "Température_Moteur":       temperature_moteur,
        "Pression_Pneus (PSI)":     pression_pneus,
        "Consommation_Carburant":   consommation_carburant,
        "État_Batterie":            etat_batterie,
        "Niveaux_Vibration":        niveaux_vibration,
    })

print(f"✅ Table maintenance remplie :")
print(f"   ├─ {nb_avec_dtc} enregistrements AVEC DTC")
print(f"   └─ {nb_sans_dtc} enregistrements SANS DTC")
print(f"✅ Table maintenance_alerts : {nb_alerts} alertes générées.")
conn.commit()
print("✅ Données sauvegardées.")

# ============================================================
# VÉRIFICATIONS & STATISTIQUES
# ============================================================

print("\n" + "="*60)
print("📊 VÉRIFICATIONS DES RELATIONS")
print("="*60)

print("\n🔗 JOIN maintenance ↔ knowledge (5 premiers) :")
df_check = pd.read_sql_query("""
    SELECT m.vehicule_id, m.dtc, m.action, m.etat_freins,
           k.symptome, k.systeme, k.gravite
    FROM maintenance m
    JOIN knowledge k ON m.dtc = k.dtc
    LIMIT 5
""", conn)
print(df_check.to_string())

print("\n🔗 JOIN maintenance ↔ thresholds via maintenance_alerts (5 premiers) :")
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

print("\n📈 Alertes par paramètre (TOP 10) :")
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

print("\n🚨 TOP 10 véhicules avec le plus d'alertes ROUGE :")
df_critiques = pd.read_sql_query("""
    SELECT m.vehicule_id,
           COUNT(*) AS nb_alertes_critiques,
           MAX(m.score_predictif) AS score_max
    FROM maintenance_alerts ma
    JOIN maintenance  m ON ma.maintenance_id = m.id
    JOIN thresholds   t ON ma.threshold_id   = t.id
    WHERE t.lampe = 'ROUGE'
    GROUP BY m.vehicule_id
    ORDER BY nb_alertes_critiques DESC
    LIMIT 10
""", conn)
print(df_critiques.to_string())

print("\n📈 TOP 10 DTC les plus fréquents :")
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

# ============================================================
# FONCTIONS DE REQUÊTE
# ============================================================

def query_dtc(code):
    print(f"\n🔎 Recherche DTC : {code}")
    print("=" * 40)
    cursor.execute("SELECT * FROM knowledge WHERE dtc = ?", (code,))
    k = cursor.fetchone()
    if k:
        print("📘 DIAGNOSTIC")
        print(f"  DTC      : {k[0]}")
        print(f"  Symptôme : {k[1]}")
        print(f"  Système  : {k[2]}")
        print(f"  Pièce    : {k[3]}")
        print(f"  Gravité  : {k[4]}")
    else:
        print("❌ Aucun diagnostic trouvé.")


def query_dtc_avancee(code):
    print(f"\n🔎 Recherche DTC avec historique : {code}")
    print("=" * 50)
    df = pd.read_sql_query("""
        SELECT k.dtc, k.symptome, k.systeme, k.piece, k.gravite,
               m.date, m.action, m.etat_freins, m.qualite_huile,
               m.anomalie_detectee, m.entretien_necessaire,
               m.score_predictif, m.vehicule_id
        FROM knowledge k
        LEFT JOIN maintenance m ON k.dtc = m.dtc
        WHERE k.dtc = ?
        ORDER BY m.date DESC
    """, conn, params=(code,))
    if df.empty:
        print("❌ Aucune information trouvée pour ce DTC.")
        return
    first = df.iloc[0]
    print("📘 DIAGNOSTIC")
    print(f"  DTC      : {first['dtc']}")
    print(f"  Symptôme : {first['symptome']}")
    print(f"  Système  : {first['systeme']}")
    print(f"  Pièce    : {first['piece']}")
    print(f"  Gravité  : {first['gravite']}")
    maint = df[df['date'].notna()]
    if not maint.empty:
        print(f"\n🛠 MAINTENANCES LIÉES ({len(maint)} enregistrements) :")
        for _, r in maint.head(5).iterrows():
            print(f"  - Véhicule {r['vehicule_id']} | {r['date']} | "
                  f"{r['action']} | Score: {r['score_predictif']:.2f}")
    else:
        print("\nℹ Aucune maintenance enregistrée pour ce DTC.")


def query_vehicle(vehicule_id):
    print(f"\n🚛 Historique véhicule : {vehicule_id}")
    print("=" * 50)
    df = pd.read_sql_query("""
        SELECT m.id, m.date, m.action, m.etat_freins, m.dtc,
               m.anomalie_detectee, m.entretien_necessaire,
               m.score_predictif,
               m.temperature_moteur, m.pression_pneus,
               m.qualite_huile, m.etat_batterie,
               k.symptome, k.systeme, k.gravite
        FROM maintenance m
        LEFT JOIN knowledge k ON m.dtc = k.dtc
        WHERE m.vehicule_id = ?
        ORDER BY m.date DESC
    """, conn, params=(str(vehicule_id),))

    if df.empty:
        print("ℹ Aucun historique trouvé.")
        return

    print(f"🛠 {len(df)} interventions trouvées\n")
    for _, r in df.iterrows():
        print(f"  📅 {r['date']} | {r['action']}")
        print(f"     Freins        : {r['etat_freins']}")
        print(f"     Score         : {r['score_predictif']:.2f}")
        print(f"     Temp. moteur  : {r['temperature_moteur']}°C  |  Pression pneus: {r['pression_pneus']} PSI")
        if r['dtc']:
            print(f"     ⚠️  DTC        : {r['dtc']} — {r['symptome']}")
            print(f"     Système       : {r['systeme']} | Gravité : {r['gravite']}")

        df_alts = pd.read_sql_query("""
            SELECT t.parametre, t.niveau_alerte, t.lampe,
                   ma.valeur_mesuree, ma.depassement, t.action, t.unite
            FROM maintenance_alerts ma
            JOIN thresholds t ON ma.threshold_id = t.id
            WHERE ma.maintenance_id = ?
        """, conn, params=(int(r['id']),))

        if not df_alts.empty:
            for _, a in df_alts.iterrows():
                lampe = a['lampe'] if a['lampe'] else "─"
                print(f"     🔔 [{lampe}] {a['parametre']} = {a['valeur_mesuree']} {a['unite']} "
                      f"({a['depassement']}) → {a['action']}")
        else:
            print(f"     ✅ Aucun dépassement de seuil détecté")
        print("     " + "─" * 44)


def query_thresholds(parametre=None):
    print(f"\n📋 Seuils techniques {'— ' + parametre if parametre else '(tous)'}")
    print("=" * 60)
    if parametre:
        df = pd.read_sql_query("""
            SELECT parametre, valeur_min, valeur_max, valeur_critique,
                   unite, lampe, niveau_alerte, action, source
            FROM thresholds WHERE parametre LIKE ?
        """, conn, params=(f"%{parametre}%",))
    else:
        df = pd.read_sql_query("""
            SELECT parametre, valeur_min, valeur_max, valeur_critique,
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
    s = cursor.fetchone()

    cursor.execute("""
        SELECT t.niveau_alerte, COUNT(*) AS nb
        FROM maintenance_alerts ma
        JOIN thresholds t ON ma.threshold_id = t.id
        GROUP BY t.niveau_alerte
    """)
    alert_counts = {row[0]: row[1] for row in cursor.fetchall()}

    header = f"""
### FLEET_STATS — Statistiques globales (base complète : {s[4]} enregistrements)
  ⚠️  ÉCHELLE score_predictif : 0.0 = faible risque → 1.0 = risque critique
  • Score prédictif   : Moyenne={s[0]:.3f} | Min={s[1]:.3f} | Max={s[2]:.3f} | Critiques (>0.8): {s[3]} ({100*s[3]/s[4]:.1f}%)
  • Anomalies         : {s[5]}/{s[4]} ({100*s[5]/s[4]:.1f}%)
  • Entretien nécess. : {s[6]}/{s[4]} ({100*s[6]/s[4]:.1f}%)
  • Qualité huile     : Moyenne={s[7]:.1f}% | Min={s[8]:.1f}% | Max={s[9]:.1f}%
  • Température moteur: Moyenne={s[10]:.1f}°C | Min={s[11]:.1f}°C | Max={s[12]:.1f}°C
  • Pression pneus    : Moyenne={s[13]:.1f} PSI | Min={s[14]:.1f} PSI | Max={s[15]:.1f} PSI

### SEUILS_ALERTES_FLEET (via table thresholds)
  • ARRÊT IMMÉDIAT : {alert_counts.get('ARRÊT IMMÉDIAT', 0)} alertes
  • SURVEILLANCE   : {alert_counts.get('SURVEILLANCE', 0)} alertes
  • Total alertes  : {sum(alert_counts.values())} sur {s[4]} enregistrements
"""
    return header


# ============================================================
# TESTS
# ============================================================

print("\n" + "="*60)
print("🧪 TESTS DES FONCTIONS")
print("="*60)

query_dtc("P0301")
query_dtc_avancee("P0301")
query_vehicle(1)
query_thresholds("Pression Pneus")

print("\n📋 FLEET STATS HEADER :")
print(get_fleet_stats_header())

conn.close()
print("\n✅ Connexion SQLite fermée.")