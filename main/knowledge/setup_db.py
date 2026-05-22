"""
╔══════════════════════════════════════════════════════════════════╗
║  TruckMind — setup_db.py                                         ║
║  Initialisation de la base SQLite3 depuis les fichiers CSV       ║
║                                                                  ║
║  Usage : python setup_db.py [--csv-dir /chemin/vers/csvs]        ║
║                                                                  ║
║  Auteure : AFFAKI Aya — EST Tétouan — IA DUT 2025-2026           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import re
import sqlite3
import hashlib
import argparse
import pandas as pd

# ─── Paths ───────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "truck_diagnostic.db")

# ─── Chemins fixes ───────────────────────────────────────────────
CSV_CODES_FIXE = r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\uploads\codes_erreur.csv"
CSV_MAINT_FIXE = r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\uploads\histoire_de_maintenance.csv"

# ─── Arguments ───────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="TruckMind — Configuration de la base de données")
parser.add_argument("--csv-dir",   default=None,           help="Répertoire des fichiers CSV (non utilisé, chemins fixes)")
parser.add_argument("--codes-csv", default=CSV_CODES_FIXE, help="Chemin vers codes_erreur.csv")
parser.add_argument("--maint-csv", default=CSV_MAINT_FIXE, help="Chemin vers histoire_de_maintenance.csv")
parser.add_argument("--force",     action="store_true",    help="Recréer la base de données même si elle existe")
args = parser.parse_args()

CSV_CODES = args.codes_csv
CSV_MAINT = args.maint_csv

if not os.path.exists(CSV_CODES):
    print(f"Erreur : fichier introuvable - {CSV_CODES}")
    sys.exit(1)
if not os.path.exists(CSV_MAINT):
    print(f"Erreur : fichier introuvable - {CSV_MAINT}")
    sys.exit(1)


def check_existing_db():
    if os.path.exists(DB_PATH) and not args.force:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM knowledge")
            n = cur.fetchone()[0]
            if n > 0:
                cur.execute("SELECT COUNT(*) FROM maintenance")
                m = cur.fetchone()[0]
                print(f"✅ Base existante trouvée : {n} DTC, {m} maintenances")
                print(f"   Utilisez --force pour recréer.")
                conn.close()
                return True
        except Exception:
            pass
        conn.close()
    return False


# ─── Helper functions ─────────────────────────────────────────────
def safe_get(row, col, default=None):
    if col in row.index and pd.notna(row[col]):
        return row[col]
    return default

def detect_system(desc):
    d = str(desc).lower()
    if "air" in d:        return "admission"
    if "temp" in d:       return "refroidissement"
    if "press" in d:      return "capteur pression"
    if "inject" in d:     return "injection"
    if "abs" in d:        return "freinage ABS"
    if "vitesse" in d:    return "transmission"
    if "ralenti" in d:    return "gestion moteur"
    return "moteur"

def detect_piece(desc):
    d = str(desc).lower()
    if "capteur" in d:                       return "capteur"
    if "injecteur" in d or "inject" in d:    return "injecteur"
    if "bobine" in d:                        return "bobine"
    if "raté" in d or "misfire" in d:        return "bougie / bobine"
    if "catalyt" in d:                       return "catalyseur"
    if "egr" in d:                           return "vanne EGR"
    if "turbo" in d or "boost" in d:         return "turbocompresseur"
    if "throttle" in d or "papillon" in d:   return "papillon des gaz"
    if "débit" in d or "massique" in d:      return "débitmètre MAF"
    if "pression" in d:                      return "capteur pression MAP"
    if "température" in d or "coolant" in d: return "sonde température"
    if "carburant" in d or "fuel" in d:      return "système carburant"
    if "abs" in d or "frein" in d:           return "système freinage"
    if "batterie" in d or "battery" in d:    return "alimentation électrique"
    return "composant générique"

def detect_gravite(code):
    c = str(code)
    if c.startswith("P03"): return "haute"
    if c.startswith("C1"):  return "haute"
    if c.startswith("P02"): return "haute"
    if c.startswith("P05"): return "moyenne"
    if c.startswith("P01"): return "moyenne"
    return "faible"

DTC_MAP = {
    "révision du moteur": {
        "bon":     ["P0300","P0301","P0302","P0303","P0304"],
        "moyen":   ["P0300","P0301","P0302","P0506","P0507"],
        "mauvais": ["P0300","P0301","P0302","P0500","P0501"],
    },
    "changement d'huile": {
        "bon":     ["P0506","P0507","P0500"],
        "moyen":   ["P0500","P0501","P0506"],
        "mauvais": ["P0500","P0501","P0300"],
    },
    "rotation des pneus": {
        "bon":     ["C1091","C1095","C1100"],
        "moyen":   ["C1091","C1100","C1200"],
        "mauvais": ["C1200","C1201","C1202"],
    },
}

def assign_dtc(row, idx):
    anomalie = int(safe_get(row, "Anomalies_Détectées", 0))
    if anomalie == 0:
        return None
    t = str(safe_get(row, "Type_Entretien", "révision du moteur")).strip().lower()
    f = str(safe_get(row, "État_Freins", "bon")).strip().lower()
    key      = next((k for k in DTC_MAP if k in t), "révision du moteur")
    etat_key = f if f in DTC_MAP[key] else "bon"
    cands    = DTC_MAP[key][etat_key]
    vid      = str(safe_get(row, "Identifiant_Véhicule", 0))
    h        = int(hashlib.md5(f"{vid}_{idx}".encode()).hexdigest(), 16)
    return cands[h % len(cands)]


# ─── Threshold data ───────────────────────────────────────────────
THRESHOLDS = [
    ("Température Moteur",            "temperature_moteur",    None,  100.0, None,  "°C",      "JAUNE", "SURVEILLANCE",   "Surveiller — risque de surchauffe",                                  "Manuel Volvo FH/FM p.5"),
    ("Température Moteur",            "temperature_moteur",    None,  105.0, None,  "°C",      "ROUGE", "ARRÊT IMMÉDIAT", "Arrêter le moteur immédiatement — refroidir 10-15 min",               "Manuel Volvo FH/FM p.24"),
    ("Pression Pneus",                "pression_pneus",        100.0, 120.0, None,  "PSI",     "VERT",  "NORMAL",         "Pression dans la plage normale (100–120 PSI)",                        "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",                "pression_pneus",         90.0, None,  None,  "PSI",     "JAUNE", "SURVEILLANCE",   "Pression basse — vérifier les pneus avant départ",                   "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus",                "pression_pneus",         None, None,   75.0, "PSI",     "ROUGE", "ARRÊT IMMÉDIAT", "Pression critique — risque d'éclatement",                             "Norme poids-lourd Volvo FH/FM"),
    ("Pression Pneus Haute",          "pression_pneus",         None, 125.0, None,  "PSI",     "ROUGE", "ARRÊT IMMÉDIAT", "Surpression — risque d'éclatement à chaud",                          "Norme poids-lourd Volvo FH/FM"),
    ("Qualité Huile",                 "qualite_huile",           40.0, None,  None,  "%",       "JAUNE", "SURVEILLANCE",   "Huile dégradée — planifier vidange sous 30 jours",                   "Manuel Volvo FH/FM p.1"),
    ("Qualité Huile",                 "qualite_huile",           None, None,   20.0, "%",       "ROUGE", "ARRÊT IMMÉDIAT", "Huile très dégradée — vidange immédiate obligatoire",                 "Manuel Volvo FH/FM p.1"),
    ("État Batterie",                 "etat_batterie",           30.0, None,  None,  "%",       "JAUNE", "SURVEILLANCE",   "Batterie faible — vérifier l'alternateur",                            "Manuel Volvo FH/FM p.84"),
    ("État Batterie",                 "etat_batterie",           None, None,   15.0, "%",       "ROUGE", "ARRÊT IMMÉDIAT", "Batterie critique — risque de panne démarrage",                       "Manuel Volvo FH/FM p.84"),
    ("Consommation Carburant",        "consommation_carburant",  None,  35.0, None,  "L/100km", "JAUNE", "SURVEILLANCE",   "Consommation anormale — vérifier injection/filtre",                  "Manuel Volvo FH/FM p.1"),
    ("Consommation Carburant",        "consommation_carburant",  None, None,   45.0, "L/100km", "ROUGE", "ARRÊT IMMÉDIAT", "Consommation critique — diagnostic immédiat requis",                  "Manuel Volvo FH/FM p.1"),
    ("Niveaux Vibration",             "niveaux_vibration",       None,   8.0, None,  "mm/s",    "JAUNE", "SURVEILLANCE",   "Vibrations anormales — vérifier roues et suspension",                "Diagnostic standard Volvo"),
    ("Niveaux Vibration",             "niveaux_vibration",       None, None,   12.0, "mm/s",    "ROUGE", "ARRÊT IMMÉDIAT", "Vibrations critiques — risque de défaillance",                       "Diagnostic standard Volvo"),
    ("Score Prédictif",               "score_predictif",         None,   0.5, None,  "score",   "JAUNE", "SURVEILLANCE",   "Risque modéré — planifier entretien sous 15 jours",                  "Modèle prédictif TruckMind"),
    ("Score Prédictif",               "score_predictif",         None, None,    0.8, "score",   "ROUGE", "ARRÊT IMMÉDIAT", "Risque critique — entretien immédiat obligatoire",                    "Modèle prédictif TruckMind"),
    ("Régime Ralenti",                None,                     550.0, 650.0, None,  "tr/min",  "VERT",  "NORMAL",         "Régime de ralenti normal entre 550 et 650 tr/min",                   "Manuel Volvo FH/FM p.25"),
    ("Pression Frein Stationnement",  None,                       5.0, None,  None,  "bar",     "ROUGE", "ARRÊT IMMÉDIAT", "Pression insuffisante — appuyer valve verrouillage",                  "Manuel Volvo FH/FM p.33"),
    ("Intervalle Vidange Huile (km)", None,                      None, None, 30000., "km",      "JAUNE", "SURVEILLANCE",   "Vidange tous les 30 000 km OU 12 mois — la première échéance prime",  "Manuel Volvo FH/FM p.1"),
    ("Intervalle Vidange Huile (mois)", None,                    None, None,   12.0, "mois",    "JAUNE", "SURVEILLANCE",   "Vidange tous les 12 mois OU 30 000 km — la première échéance prime",  "Manuel Volvo FH/FM p.1"),
]


# ─── Main setup ───────────────────────────────────────────────────
def main():
    print("""
╔══════════════════════════════════════════════════════╗
║  🚛 TruckMind — Database Setup v2.0                  ║
║  Auteure : AFFAKI Aya — EST Tétouan — IA DUT         ║
╚══════════════════════════════════════════════════════╝
""")

    if check_existing_db():
        sys.exit(0)

    # ── Validate CSV files ─────────────────────────────────────────
    for path, name in [(CSV_CODES, "codes_erreur.csv"), (CSV_MAINT, "histoire_de_maintenance.csv")]:
        if not os.path.exists(path):
            print(f"❌ Fichier introuvable : {path}")
            print(f"   Spécifiez le chemin avec --codes-csv / --maint-csv")
            sys.exit(1)

    # ── Connect & create tables ────────────────────────────────────
    print(f"📁 Base de données : {DB_PATH}")
    if os.path.exists(DB_PATH) and args.force:
        os.remove(DB_PATH)
        print("🗑️  Base existante supprimée (--force)")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    cur = conn.cursor()

    # Table : knowledge
    cur.execute("""
    CREATE TABLE IF NOT EXISTS knowledge (
        dtc      TEXT PRIMARY KEY,
        symptome TEXT,
        systeme  TEXT,
        piece    TEXT,
        gravite  TEXT
    )""")

    # Table : thresholds
    cur.execute("""
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
        UNIQUE(parametre, niveau_alerte)
    )""")

    # Table : maintenance
    # ✅ id = TEXT PRIMARY KEY (ex: V0001) — pas d'AUTOINCREMENT
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maintenance (
        id                     TEXT PRIMARY KEY,
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
    )""")

    # Table : maintenance_alerts
    # ✅ maintenance_id = TEXT pour correspondre à maintenance.id
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maintenance_alerts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        maintenance_id   TEXT    NOT NULL,
        threshold_id     INTEGER NOT NULL,
        valeur_mesuree   REAL,
        depassement      TEXT,
        FOREIGN KEY (maintenance_id) REFERENCES maintenance(id),
        FOREIGN KEY (threshold_id)   REFERENCES thresholds(id)
    )""")

    # Indexes for performance
    cur.execute("CREATE INDEX IF NOT EXISTS idx_maint_vehicule ON maintenance(vehicule_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_maint_dtc      ON maintenance(dtc)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_maint_score    ON maintenance(score_predictif DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_maint   ON maintenance_alerts(maintenance_id)")
    print("✅ Tables & index créés")

    # ── Fill thresholds ────────────────────────────────────────────
    cur.executemany("""
    INSERT OR IGNORE INTO thresholds
        (parametre, colonne_csv, valeur_min, valeur_max, valeur_critique,
         unite, lampe, niveau_alerte, action, source)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    """, THRESHOLDS)
    nb_t = cur.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0]
    print(f"✅ Thresholds : {nb_t} seuils insérés")

    # ── Fill knowledge ─────────────────────────────────────────────
    print(f"📂 Chargement : {CSV_CODES}")
    codes_df = pd.read_csv(CSV_CODES)
    for _, row in codes_df.iterrows():
        dtc  = safe_get(row, "Code", "UNKNOWN")
        desc = safe_get(row, "Description", "Aucune description")
        cur.execute("INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?,?)",
                    (dtc, desc, detect_system(desc), detect_piece(desc), detect_gravite(str(dtc))))
    nb_k = cur.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    print(f"✅ Knowledge : {nb_k} codes DTC insérés")

    # ── Fill maintenance ───────────────────────────────────────────
    print(f"📂 Chargement : {CSV_MAINT}")
    maint_df = pd.read_csv(CSV_MAINT)

    # Pre-load thresholds with csv columns
    cur.execute("SELECT id, colonne_csv, valeur_min, valeur_max, valeur_critique FROM thresholds WHERE colonne_csv IS NOT NULL")
    thresh_actifs = cur.fetchall()

    nb_dtc = nb_nodtc = nb_alerts = 0
    BATCH = 200

    for idx, row in maint_df.iterrows():
        # ✅ Lecture de l'id depuis le CSV (ex: V0001)
        row_id = str(safe_get(row, "Identifiant_Véhicule", f"ROW_{idx}"))

        vid            = row_id
        date           = safe_get(row, "Date_Dernier_Entretien", "")
        action         = safe_get(row, "Type_Entretien", "maintenance")
        etat_freins    = safe_get(row, "État_Freins", "inconnu")
        qualite_huile  = safe_get(row, "Qualité_Huile", None)
        anomalie       = int(safe_get(row, "Anomalies_Détectées", 0))
        entretien      = int(safe_get(row, "Entretien_Nécessaire", 0))
        score          = safe_get(row, "Score_Prédictif", 0)
        temp           = safe_get(row, "Température_Moteur", None)
        pneus          = safe_get(row, "Pression_Pneus", None)
        carbu          = safe_get(row, "Consommation_Carburant", None)
        batt           = safe_get(row, "État_Batterie", None)
        vibr           = safe_get(row, "Niveaux_Vibration", None)

        dtc = assign_dtc(row, idx)
        if dtc: nb_dtc   += 1
        else:   nb_nodtc += 1

        # ✅ id inclus dans l'INSERT
        cur.execute("""
        INSERT OR IGNORE INTO maintenance
            (id, vehicule_id, dtc, date, action, etat_freins, qualite_huile,
             anomalie_detectee, entretien_necessaire, score_predictif,
             temperature_moteur, pression_pneus, consommation_carburant,
             etat_batterie, niveaux_vibration)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row_id, vid, dtc, date, action, etat_freins, qualite_huile,
              anomalie, entretien, score, temp, pneus, carbu, batt, vibr))

        valeurs = {
            "qualite_huile":          qualite_huile,
            "score_predictif":        score,
            "temperature_moteur":     temp,
            "pression_pneus":         pneus,
            "consommation_carburant": carbu,
            "etat_batterie":          batt,
            "niveaux_vibration":      vibr,
        }

        for (tid, col_csv, v_min, v_max, v_crit) in thresh_actifs:
            val = valeurs.get(col_csv)
            if val is None:
                continue
            dep = None
            if v_crit is not None:
                if v_min is None and val >= v_crit:       dep = "CRITIQUE"
                elif v_min is not None and val <= v_crit: dep = "CRITIQUE"
            if not dep and v_max is not None and val > v_max: dep = "MAX"
            if not dep and v_min is not None and val < v_min: dep = "MIN"
            if dep:
                cur.execute(
                    "INSERT INTO maintenance_alerts VALUES (NULL,?,?,?,?)",
                    (row_id, tid, val, dep)
                )
                nb_alerts += 1

        if idx % BATCH == 0:
            conn.commit()
            print(f"  ↳ {idx}/{len(maint_df)} lignes traitées...", end="\r")

    conn.commit()
    nb_m = cur.execute("SELECT COUNT(*) FROM maintenance").fetchone()[0]
    print(f"\n✅ Maintenance : {nb_m} enregistrements ({nb_dtc} avec DTC, {nb_nodtc} sans)")
    print(f"✅ Alerts      : {nb_alerts} dépassements de seuil détectés")

    conn.close()
    print(f"""
╔══════════════════════════════════════════════════════╗
║  Base de données créée avec succès!                  ║
║  Chemin : {DB_PATH[:43]:<43}                         ║
╚══════════════════════════════════════════════════════╝

  Lancez maintenant : python app.py
""")


if __name__ == "__main__":
    main()