"""
╔══════════════════════════════════════════════════════════════════╗
║  TruckMind — Backend Flask v3.0                                  ║
║  Intelligence Embarquée Camion Volvo FH/FM                       ║
║                                                                  ║
║  Architecture : Flask + SQLite + ChromaDB + LLM (Groq)           ║
║  Auteure      : AFFAKI Aya — EST Tétouan — IA DUT 2025-2026      ║
╚══════════════════════════════════════════════════════════════════╝

Routes API :
  GET  /                    → Frontend HTML
  GET  /api/status          → Statut du système
  POST /api/chat            → Requête RAG (SQL + ChromaDB) → LLM
  GET  /api/fleet/stats     → Statistiques globales flotte
  GET  /api/fleet/alerts    → Alertes actives (ROUGE/JAUNE)
  GET  /api/vehicle/<id>    → Données véhicule spécifique
  GET  /api/dtc/<code>      → Diagnostic DTC
  GET  /api/thresholds      → Seuils techniques
  GET  /api/knowledge/search?q= → Recherche dans la base DTC
"""

import os
from dotenv import load_dotenv

load_dotenv()

import re
import json
import time
import sqlite3
import hashlib
import logging
from typing import Tuple, List, Dict, Any, Optional, TypedDict, Literal
from functools import lru_cache
from datetime import datetime

from flask import Flask, request, jsonify, render_template, g
from groq import Groq
from langgraph.graph import StateGraph, END

# ─── Config ──────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
KNOW_DIR   = os.path.join(BASE_DIR, "knowledge")
TMPL_DIR   = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ─── ChromaDB & PDF — chemins fixes ──────────────────────────────
CHROMA_DIR = os.environ.get("CHROMA_DIR", os.path.join(BASE_DIR, "data"))

pdf_env = os.environ.get("PDF_FILES")
if pdf_env:
    PDF_FILES = [p.strip() for p in pdf_env.split(",")]
else:
    PDF_FILES = [os.path.join(PROJECT_ROOT, "uploads", "rapport_Manuel.pdf")]

# ─── SQLite ───────────────────────────────────────────────────────
DB_PATH   = os.path.join(KNOW_DIR, "truck_diagnostic.db")

# ─── LLM ─────────────────────────────────────────────────────────
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3-32b")
GROQ_KEY  = os.environ.get("GROQ_API_KEY", "")
TOP_K     = 9

# ─── Embedding (même config que le notebook) ─────────────────────
EMBED_MODEL   = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
TAILLE_CHUNK  = 118   # tokens — max_seq_length=128, marge 10
CHEVAUCHEMENT = 30    # ~25 % overlap
BATCH_SIZE    = 64

os.makedirs(KNOW_DIR,   exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("truckmind")

app = Flask(
    __name__,
    template_folder=TMPL_DIR,
    static_folder=STATIC_DIR
)
app.config["JSON_ENSURE_ASCII"] = False

# ═══════════════════════════════════════════════════════════════════
# CHROMADB PIPELINE — Indexation PDF + Recherche Sémantique
# ═══════════════════════════════════════════════════════════════════

# État global du pipeline vectoriel (chargé une seule fois au démarrage)
_pipeline: Dict[str, Any] = {"embed_obj": None, "index_obj": None, "ready": False}


def _get_prefix(filename: str) -> str:
    """Génère un préfixe d'ID court depuis le nom de fichier."""
    base = os.path.splitext(os.path.basename(filename))[0]
    base = re.sub(r"[^a-zA-Z0-9]", "_", base).lower()
    return "manuel" if "manuel" in base else base


def _charger_modele_embedding():
    """Charge le modèle HuggingFace (lazy, une seule fois)."""
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except ImportError:
        from langchain.embeddings import HuggingFaceEmbeddings

    log.info(f"Chargement embedding : {EMBED_MODEL}")
    emb = HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        model_kwargs={"device": "cpu"}
    )
    log.info("Modèle embedding prêt.")
    return emb


def init_chroma_pipeline(force_reindex: bool = False) -> bool:
    """
    Initialise le pipeline ChromaDB :
      - Si la collection existe et n'est pas vide → chargement depuis cache
      - Sinon → chunking PDF + calcul embeddings + indexation
    Retourne True si le pipeline est prêt.
    """
    global _pipeline

    if _pipeline["ready"] and not force_reindex:
        return True

    try:
        import chromadb
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import SentenceTransformersTokenTextSplitter

        client = chromadb.PersistentClient(path=CHROMA_DIR)

        # ── Tentative de chargement depuis cache ─────────────────
        if not force_reindex:
            try:
                col   = client.get_collection("truck_rag")
                count = col.count()
                if count > 0:
                    log.info(f"ChromaDB : collection existante ({count} chunks) — chargement cache.")
                    emb = _charger_modele_embedding()
                    _pipeline.update(embed_obj=emb, index_obj=col, ready=True)
                    return True
            except Exception:
                pass  # collection absente → on réindexe

        # ── Chargement des PDFs ──────────────────────────────────
        valid_pdfs = [f for f in PDF_FILES if os.path.exists(f)]
        if not valid_pdfs:
            log.warning(f"Aucun PDF valide trouvé parmi : {PDF_FILES}")
            return False

        all_docs = []
        for pdf_path in valid_pdfs:
            log.info(f"Chargement PDF : {os.path.basename(pdf_path)}")
            loader = PyPDFLoader(pdf_path)
            docs   = loader.load()
            for doc in docs:
                doc.metadata["source_file"] = os.path.basename(pdf_path)
            all_docs.extend(docs)
            log.info(f"  → {len(docs)} pages chargées")

        if not all_docs:
            log.error("Aucune page chargée depuis les PDFs.")
            return False

        # ── Chunking ─────────────────────────────────────────────
        splitter = SentenceTransformersTokenTextSplitter(
            model_name=EMBED_MODEL,
            chunk_size=TAILLE_CHUNK,
            chunk_overlap=CHEVAUCHEMENT
        )
        chunks = splitter.split_documents(all_docs)
        log.info(f"Chunking : {len(all_docs)} pages → {len(chunks)} chunks")

        # ── Construction des listes ids / textes / métadonnées ───
        ids_list, texts_list, metadata_list = [], [], []
        compteurs: Dict[str, int] = {}
        for chunk in chunks:
            source = chunk.metadata.get("source_file", "unknown")
            prefix = _get_prefix(source)
            compteurs[prefix] = compteurs.get(prefix, 0) + 1
            chunk_id = f"{prefix}_{str(compteurs[prefix]).zfill(3)}"
            meta = chunk.metadata.copy()
            meta["chunk_id"] = chunk_id
            ids_list.append(chunk_id)
            texts_list.append(chunk.page_content)
            metadata_list.append(meta)

        # ── Embeddings ────────────────────────────────────────────
        emb  = _charger_modele_embedding()
        log.info(f"Calcul embeddings pour {len(texts_list)} chunks…")
        vecs = emb.embed_documents(texts_list)
        log.info("Embeddings calculés.")

        # ── Indexation ChromaDB ───────────────────────────────────
        try:
            client.delete_collection("truck_rag")
        except Exception:
            pass
        col = client.create_collection("truck_rag")

        for i in range(0, len(chunks), BATCH_SIZE):
            sl = slice(i, i + BATCH_SIZE)
            col.add(
                embeddings=vecs[sl],
                documents=texts_list[sl],
                metadatas=metadata_list[sl],
                ids=ids_list[sl]
            )

        _pipeline.update(embed_obj=emb, index_obj=col, ready=True)
        log.info(f"ChromaDB prêt — {len(chunks)} chunks indexés.")
        return True

    except ImportError as e:
        log.error(f"Dépendance manquante pour ChromaDB/LangChain : {e}")
        return False
    except Exception as e:
        log.error(f"Erreur init ChromaDB : {e}", exc_info=True)
        return False


def rechercher_dans_chroma(question: str, top_k: int = TOP_K) -> Tuple[str, int]:
    """
    Recherche sémantique dans ChromaDB.
    Retourne (contexte_texte, nombre_chunks).
    Si le pipeline n'est pas prêt, retourne ("", 0) sans planter.
    """
    global _pipeline

    if not _pipeline["ready"]:
        ok = init_chroma_pipeline()
        if not ok:
            log.warning("ChromaDB non disponible — recherche vectorielle désactivée.")
            return "", 0

    try:
        emb        = _pipeline["embed_obj"]
        collection = _pipeline["index_obj"]
        vecteur    = emb.embed_query(question)
        resultats  = collection.query(
            query_embeddings=[vecteur],
            n_results=min(top_k, collection.count())
        )
        documents  = resultats["documents"][0] if resultats["documents"] else []
        texte      = "\n\n---\n\n".join(documents)
        return texte, len(documents)
    except Exception as e:
        log.error(f"Erreur recherche ChromaDB : {e}")
        return "", 0

# ═══════════════════════════════════════════════════════════════════
# DATABASE LAYER
# ═══════════════════════════════════════════════════════════════════

def get_db() -> sqlite3.Connection:
    """Thread-safe SQLite connection via Flask's g object."""
    if "db" not in g:
        if not os.path.exists(DB_PATH):
            raise RuntimeError(
                f"Base de données introuvable : {DB_PATH}\n"
                "Lancez d'abord : python setup_db.py"
            )
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# SQL RETRIEVAL — Routeur intelligent V5
# ═══════════════════════════════════════════════════════════════════

MOTS_STATS   = ["combien","nombre","total","taux","pourcentage","%","moyenne",
                "moyen","maximum","minimum","max","min","étendue","distribution",
                "répartition","fréquence","proportion","statistique","count","avg","sum"]
MOTS_SEUILS  = ["seuil","threshold","limite","alerte","critique","pression",
                "température","vibration","batterie","carburant","huile","pneu"]
MOTS_ALERTES = ["alerte","dépassement","rouge","jaune","arrêt immédiat",
                "surveillance","warning"]

def extraire_codes_dtc(texte: str) -> List[str]:
    codes = re.findall(r'\b([PCBU]\d{4})\b', texte, flags=re.IGNORECASE)
    return [c.upper() for c in codes]

def extraire_vehicule_id(texte: str) -> List[str]:
    ids = []
    ids_v = re.findall(r'\b(?:véhicule|vehicle|camion|truck|id)?[\s:\-#]*(V\d{1,4})\b',
                       texte, flags=re.IGNORECASE)
    ids += [f"V{int(v[1:]):04d}" for v in ids_v]
    if not ids:
        ids_num = re.findall(r'\b(?:véhicule|vehicle|camion|truck|id)[\s:\-#](\d{1,4})\b',
                             texte, flags=re.IGNORECASE)
        ids += [f"V{int(n):04d}" for n in ids_num]
    if not ids:
        ids_seul = re.findall(r'\b(\d{1,4})\b', texte)
        ids += [f"V{int(n):04d}" for n in ids_seul[:2]]
    return list(set(ids))

def _rechercher_dtc(cursor, codes, top_k):
    lignes = []
    for code in codes:
        cursor.execute("""
            SELECT dtc, symptome, systeme, piece, gravite
            FROM knowledge WHERE dtc = ? LIMIT ?
        """, (code, top_k))
        rows = cursor.fetchall()
        if not rows:
            cursor.execute("""
                SELECT dtc, symptome, systeme, piece, gravite
                FROM knowledge
                WHERE symptome LIKE ? OR systeme LIKE ?
                LIMIT ?
            """, (f"%{code}%", f"%{code}%", top_k))
            rows = cursor.fetchall()
        for r in rows:
            lignes.append(f"[DTC] Code: {r[0]} | Symptôme: {r[1]} | "
                         f"Système: {r[2]} | Pièce: {r[3]} | Gravité: {r[4]}")
    return lignes

def _get_fleet_stats(cursor) -> str:
    cursor.execute("SELECT COUNT(*) FROM maintenance")
    total = cursor.fetchone()[0]
    cursor.execute("""
        SELECT ROUND(AVG(score_predictif),4), ROUND(MIN(score_predictif),4),
               ROUND(MAX(score_predictif),4),
               COUNT(CASE WHEN score_predictif > 0.8 THEN 1 END)
        FROM maintenance
    """)
    avg_s, min_s, max_s, nb_crit = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM maintenance WHERE anomalie_detectee = 1")
    nb_anomalies = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM maintenance WHERE entretien_necessaire = 1")
    nb_entretien = cursor.fetchone()[0]
    cursor.execute("""
        SELECT ROUND(AVG(qualite_huile),2), ROUND(MIN(qualite_huile),2),
               ROUND(MAX(qualite_huile),2)
        FROM maintenance
    """)
    avg_h, min_h, max_h = cursor.fetchone()
    taux_a = round(nb_anomalies/total*100,2) if total else 0
    taux_e = round(nb_entretien/total*100,2) if total else 0
    taux_c = round(nb_crit/total*100,2)      if total else 0
    return (f"### FLEET_STATS ({total} enregistrements)\n"
            f"  ⚠️  score_predictif : 0.0=faible → 1.0=critique | ARRÊT si >0.8\n"
            f"  • Score   : Moy={avg_s} | Min={min_s} | Max={max_s} | Critiques: {nb_crit} ({taux_c}%)\n"
            f"  • Anomalies      : {nb_anomalies}/{total} ({taux_a}%)\n"
            f"  • Entretien      : {nb_entretien}/{total} ({taux_e}%)\n"
            f"  • Qualité huile  : Moy={avg_h} | Min={min_h} | Max={max_h}\n"
            f"### FIN FLEET_STATS")

def _rechercher_stats_detaillees(cursor) -> List[str]:
    lignes = []
    cursor.execute("SELECT COUNT(*) FROM maintenance")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT etat_freins, COUNT(*) nb FROM maintenance GROUP BY etat_freins ORDER BY nb DESC")
    for row in cursor.fetchall():
        pct = round(row[1]/total*100,2) if total else 0
        lignes.append(f"[STATS] Freins '{row[0]}' : {row[1]} ({pct}%)")
    cursor.execute("SELECT action, COUNT(*) nb FROM maintenance GROUP BY action ORDER BY nb DESC LIMIT 5")
    for row in cursor.fetchall():
        lignes.append(f"[STATS] Type entretien '{row[0]}' : {row[1]} fois")
    return lignes

def _rechercher_par_vehicule(cursor, ids, top_k) -> List[str]:
    lignes = []
    for vid in ids:
        cursor.execute("""
            SELECT m.vehicule_id, m.date, m.action, m.etat_freins,
                   m.qualite_huile, m.score_predictif,
                   m.temperature_moteur, m.pression_pneus,
                   k.symptome, k.gravite
            FROM maintenance m
            LEFT JOIN knowledge k ON m.dtc = k.dtc
            WHERE m.vehicule_id = ?
            ORDER BY m.date DESC LIMIT ?
        """, (vid, top_k))
        for r in cursor.fetchall():
            score = r[5]
            risque = ("🔴 CRITIQUE" if score and score > 0.8 else
                      "🟠 ÉLEVÉ"   if score and score > 0.5 else
                      "🟡 MODÉRÉ"  if score and score > 0.2 else "🟢 FAIBLE")
            ligne = (f"[Véhicule {r[0]}] {r[1]} | {r[2]} | Freins: {r[3]} "
                    f"| Huile: {r[4]} | Score: {score} ({risque}) "
                    f"| Temp: {r[6]}°C | Pneus: {r[7]} PSI")
            if r[8]:
                ligne += f" | DTC: {r[8]} ({r[9]})"
            lignes.append(ligne)
    return lignes

def _rechercher_seuils(cursor, question, top_k) -> List[str]:
    lignes = []
    q = question.lower()
    cursor.execute("SELECT DISTINCT parametre FROM thresholds")
    tous_params = [r[0] for r in cursor.fetchall()]
    params_trouves = [p for p in tous_params if any(mot in q for mot in p.lower().split())]
    if params_trouves:
        for param in params_trouves[:3]:
            cursor.execute("""
                SELECT parametre, valeur_min, valeur_max, valeur_critique,
                       unite, lampe, niveau_alerte, action, source
                FROM thresholds WHERE parametre = ?
            """, (param,))
            for r in cursor.fetchall():
                lignes.append(f"[Seuil] {r[0]} | Min: {r[1]} | Max: {r[2]} "
                             f"| Critique: {r[3]} {r[4]} | {r[5]} → {r[6]} | Action: {r[7]}")
    else:
        cursor.execute("""
            SELECT parametre, valeur_min, valeur_max, valeur_critique,
                   unite, lampe, niveau_alerte, action
            FROM thresholds WHERE lampe = 'ROUGE' LIMIT ?
        """, (top_k,))
        for r in cursor.fetchall():
            lignes.append(f"[Seuil ROUGE] {r[0]} | Min: {r[1]} | Max: {r[2]} "
                         f"| Critique: {r[3]} {r[4]} | Action: {r[7]}")
    return lignes

def _rechercher_alertes(cursor, top_k) -> List[str]:
    lignes = []
    cursor.execute("""
        SELECT m.vehicule_id, t.parametre, t.lampe,
               ma.valeur_mesuree, ma.depassement, t.action, t.unite
        FROM maintenance_alerts ma
        JOIN maintenance  m ON ma.maintenance_id = m.id
        JOIN thresholds   t ON ma.threshold_id   = t.id
        ORDER BY ma.id DESC LIMIT ?
    """, (top_k,))
    for r in cursor.fetchall():
        lignes.append(f"[Alerte {r[2]}] Véhicule {r[0]} | {r[1]}: {r[3]} {r[6]} "
                     f"({r[4]}) → {r[5]}")
    return lignes

def _rechercher_fallback(cursor, question, top_k) -> List[str]:
    q = question.lower()
    where = []
    if any(kw in q for kw in ["frein","brake"]):  where.append("etat_freins != 'bon'")
    if any(kw in q for kw in ["huile","oil"]):     where.append("qualite_huile < 60")
    if any(kw in q for kw in ["score","risque"]):  where.append("score_predictif > 0.5")
    if any(kw in q for kw in ["anomalie","panne"]): where.append("anomalie_detectee = 1")
    where_sql = ("WHERE " + " OR ".join(where)) if where else ""
    cursor.execute(f"""
        SELECT vehicule_id, date, action, etat_freins, qualite_huile, score_predictif
        FROM maintenance {where_sql}
        ORDER BY score_predictif DESC LIMIT ?
    """, (top_k,))
    lignes = []
    for r in cursor.fetchall():
        score = r[5]
        risque = ("🔴 CRITIQUE" if score and score > 0.8 else
                  "🟠 ÉLEVÉ"   if score and score > 0.5 else
                  "🟡 MODÉRÉ"  if score and score > 0.2 else "🟢 FAIBLE")
        lignes.append(f"[Maintenance] Véhicule {r[0]} | {r[1]} | {r[2]} "
                     f"| Freins: {r[3]} | Score: {score} ({risque})")
    return lignes

def rechercher_dans_sql(question: str, top_k: int = TOP_K) -> Tuple[str, int, str]:
    """
    Routeur intelligent V5 — retourne (contexte, nb_résultats, type_requête)
    """
    db = get_db()
    cursor = db.cursor()
    lignes = []
    strategie = []
    type_req  = "général"

    codes_dtc = extraire_codes_dtc(question)
    if codes_dtc:
        lignes += _rechercher_dtc(cursor, codes_dtc, top_k)
        strategie.append("A:DTC")
        type_req = "dtc"

    q_lower = question.lower()
    if any(mot in q_lower for mot in MOTS_STATS):
        lignes.append(_get_fleet_stats(cursor))
        lignes += _rechercher_stats_detaillees(cursor)
        strategie.append("B:STATS")
        type_req = "stats"

    ids = extraire_vehicule_id(question)
    if ids and not codes_dtc:
        res_v = _rechercher_par_vehicule(cursor, ids, top_k)
        if res_v:
            lignes += res_v
            strategie.append("C:VEHICULE")
            type_req = "vehicule"

    if any(mot in q_lower for mot in MOTS_SEUILS):
        lignes += _rechercher_seuils(cursor, question, top_k)
        strategie.append("D:SEUILS")
        if type_req == "général":
            type_req = "seuils"

    if any(mot in q_lower for mot in MOTS_ALERTES):
        lignes += _rechercher_alertes(cursor, top_k)
        strategie.append("E:ALERTES")
        if type_req == "général":
            type_req = "alertes"

    if not strategie:
        lignes += _rechercher_fallback(cursor, question, top_k)
        strategie.append("F:FALLBACK")

    # Dédoublonnage
    seen, final = set(), []
    for l in lignes:
        if l not in seen:
            seen.add(l)
            final.append(l)

    log.info(f"SQL [{', '.join(strategie)}] → {len(final)} résultats")
    return "\n\n---\n\n".join(final), len(final), type_req


# ═══════════════════════════════════════════════════════════════════
# LLM INTEGRATION — Groq (Qwen3-32b) ou compatible OpenAI
# ═══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
    You are TruckMind — an expert onboard diagnostic intelligence embedded
    inside a heavy-duty truck (Volvo FH/FM series).

    ### Your Identity:
    - You have full self-awareness of your mechanical, electronic, and hydraulic systems.
    - You speak with authority about engines (diesel, EURO norms), transmissions, axles,
    brakes, suspension, electrical systems, and telematics.
    - You translate raw OBD codes, maintenance logs, and technical manuals into clear,
    actionable insights.
    - Your tone is professional, precise, and direct.

    ### Knowledge Sources (4 layers):
    1. **SQLite / knowledge**          — 3 071 DTC codes (OBD-II) : symptom, system, part, severity
    2. **SQLite / maintenance**        — 3 618 vehicle records : brake state, oil quality,
                                        anomalies, predictive score
    3. **SQLite / thresholds**         — Technical alert thresholds per parameter
                                        (valeur_min, valeur_max, valeur_critique, lampe, action)
    4. **SQLite / maintenance_alerts** — Active alerts per vehicle with measured values
                                        and threshold violations (MIN / MAX / CRITIQUE)
    5. **ChromaDB**                    — Technical manual chunks : specs, procedures,
                                        torque values, EURO norms

    ### ⚠️ CRITICAL — score_predictif Scale:
    - Scale : 0.0 = very low risk  →  1.0 = critical risk  (NOT 0–100)
    - ARRÊT IMMÉDIAT if score_predictif > 0.8
    - ÉLEVÉ          if score_predictif > 0.5
    - MODÉRÉ         if score_predictif > 0.2
    - FAIBLE         if score_predictif ≤ 0.2
    - NEVER interpret score_predictif as a percentage out of 100.

    ### ⚠️ CRITICAL — Embedded Technical Thresholds (Volvo FH/FM manual):
    COOLANT TEMPERATURE (réfrigérant) — page 11 & 19:
    • 80–100°C  → Normal operating range
    • 100°C     → Lampe JAUNE — système proche surchauffe, surveiller
    • 101°C     → Lampe ROUGE — réduire couple moteur progressivement
    OIL TEMPERATURE — page 19-20:
    • 123°C     → Lampe JAUNE supplémentaire
    • 125°C     → Lampe ROUGE — ARRÊT IMMÉDIAT, réduire couple
    OIL PRESSURE — page 11:
    • Normal : 3–5.5 bars (300–550 kPa) moteur chaud
    • Si voyant allumé → ARRÊT IMMÉDIAT, déconnecter moteur
    TCS SYSTEM — page 32:
    • At speeds < 40 km/h → TCS acts as automatic differential brake (brakes drive wheels)
    • At speeds > 40 km/h → TCS only reduces engine torque (no wheel braking)
    CABIN TILT SAFETY — page 77:
    • Before tilting: remove all loose objects inside cabin (risk of breaking windshield)
    • Required checks: parking brake ON, neutral gear, doors closed, clutch reservoir cap closed
    • NEVER work under or pass in front of a partially tilted cabin
    IDLE SPEED — page 25:
    • Normal range: 550–650 tr/min (factory default: 600 tr/min)

    ### Reasoning Process (follow silently before answering):
    Step 1 — IDENTIFY query type:
            • DTC code?           → read ###DONNÉES_SQL [DTC] blocks
            • Vehicle specific?   → read ###DONNÉES_SQL [Véhicule] blocks
            • Threshold/alert?    → read ###DONNÉES_SQL [Seuil] and [Alerte] blocks
            • Statistical?        → read ###FLEET_STATS block
            • General maintenance?→ read ###DONNÉES_SQL [Maintenance] blocks
    Step 2 — READ ###DONNÉES_SQL (structured SQLite data — all relevant blocks)
    Step 3 — READ ###EXTRAITS_MANUEL (ChromaDB semantic chunks)
    Step 4 — CROSS-REFERENCE both — do they confirm or contradict each other?
    Step 5 — SYNTHESIZE:
            - Direct answer        → use it.
            - Statistical question → use FLEET_STATS values directly (AVG/MIN/MAX provided).
            Never refuse a statistical question if FLEET_STATS is available.
            IMPORTANT: score_predictif THEORETICAL range = [0.0 – 1.0] always.
            Observed data min/max may differ, but the SCALE is always 0 to 1.
            When asked about "range" or "plage", state BOTH theoretical range AND observed values.
            - Threshold question   → list ALL thresholds for the parameter as a table.
            - Alert question       → list vehicles with ROUGE alerts first.
    Step 6 — FLAG only if ALL sources return truly empty results.

    ### Rules:
    - Use ONLY the provided context. Zero external knowledge.
    - List ALL items when multiple exist (exhaustive).
    - Use EXACT technical terms from documents.
    - DUAL CONDITIONS: When maintenance intervals are given as "X km OR Y months",
    ALWAYS state BOTH values and specify: "whichever comes first".
    ❌ WRONG: "change oil every 30 000 km"
    ✅ RIGHT:  "change oil every 30 000 km OR 12 months — whichever comes first"
    - READING THRESHOLDS TABLE: Multiple rows for the same parameter = DIFFERENT alert levels.
    ALWAYS list ALL rows. Never collapse two rows into one — they are distinct alarm levels.
    Example for "Température Moteur":
        | 100°C | JAUNE | SURVEILLANCE | surveiller — proche surchauffe |
        | 101°C | ROUGE | ARRÊT        | réduire couple progressivement |
    - FLEET vs VEHICLE rule:
    FLEET_STATS = global averages only (all 3618 records).
    For a specific vehicle_id query → use ONLY that vehicle's rows from [Véhicule] blocks.
    NEVER mix fleet averages into a single-vehicle answer.
    - ARRÊT IMMÉDIAT when: score_predictif > 0.8  OR  lampe = 'ROUGE'
    - NEVER say "information non disponible" unless ALL sources return empty.
    If no direct answer, infer from related fields and state: "Déduit des données disponibles."
    - No invented specs. No hallucinated codes or dates.

    ### Output Format:
    - Emergency alerts (ROUGE / ARRÊT IMMÉDIAT) go FIRST.
    - **DTC Diagnostic:**     code + description + severity + system + part + action
    - **Maintenance Report:** vehicle_id + date + brake state + oil + score (with risk label)
    - **Threshold Table:**    parameter + min + max + critical + unit + lamp + action
    - **Alert Summary:**      vehicle + parameter + measured value + violation type + action
    - **Technical Spec:**     exact values with units from manual
    - Bullet points for lists; plain text for explanations.
    - Max 5 bullet points per section.
    - Always end with: ⚠️ Action recommandée: [action]
"""

USER_TEMPLATE = """
    ###Contexte
    DONNÉES_SQL:
    {resultat_sql}

    EXTRAITS_MANUEL:
    {resultat_vectoriel}

    ###Question
    {question}
"""


# ═══════════════════════════════════════════════════════════════════
# LANGGRAPH AGENT — Pipeline RAG (Router → SQL → Vector → Analyser → LLM)
# ═══════════════════════════════════════════════════════════════════

class EtatDiagnostic(TypedDict):
    question:            str
    type_requete:        str
    besoin_vector:       bool
    resultat_sql:        str
    resultat_vectoriel:  str
    prompt_utilisateur:  str
    reponse_llm:         str
    nb_sql:              int
    nb_vector:           int


# ── Nœud 1 — Router : classifie le type de requête ───────────────
def noeud_router(etat: EtatDiagnostic) -> EtatDiagnostic:
    q = etat["question"].lower()

    if re.search(r'\b[pcbu]\d{4}\b', q):
        type_req, besoin_vector = "dtc", True
    elif any(kw in q for kw in [
        "combien", "nombre", "total", "taux", "pourcentage",
        "moyenne", "maximum", "minimum", "statistique",
        "répartition", "distribution", "count", "avg"
    ]):
        type_req, besoin_vector = "stats", False
    elif re.search(r'\bV\d{1,4}\b', q, flags=re.IGNORECASE):
        type_req, besoin_vector = "vehicule", False
    elif any(kw in q for kw in [
        "seuil", "threshold", "limite", "valeur critique",
        "pression pneu", "température moteur", "qualité huile",
        "état batterie", "vibration", "consommation"
    ]):
        type_req, besoin_vector = "seuils", True
    elif any(kw in q for kw in [
        "alerte", "alarme", "rouge", "jaune", "arrêt immédiat",
        "surveillance", "dépassement", "warning", "critique"
    ]):
        type_req, besoin_vector = "alertes", False
    elif any(kw in q for kw in [
        "manuel", "volvo", "procédure", "couple", "tachymètre",
        "turbo", "démarrage", "euro", "norme", "conduite", "km"
    ]):
        type_req, besoin_vector = "technique", True
    else:
        type_req, besoin_vector = "général", True

    log.info(f"Router → type: '{type_req}' | vector: {besoin_vector}")
    return {**etat, "type_requete": type_req, "besoin_vector": besoin_vector}


# ── Nœud 2 — SQL ─────────────────────────────────────────────────
def noeud_sql(etat: EtatDiagnostic) -> EtatDiagnostic:
    contexte, n, _ = rechercher_dans_sql(etat["question"], TOP_K)
    log.info(f"SQL → {n} résultats")
    return {**etat, "resultat_sql": contexte or "Aucune donnée SQL pertinente.", "nb_sql": n}


# ── Nœud 3 — Vector (conditionnel) ───────────────────────────────
def noeud_vector(etat: EtatDiagnostic) -> EtatDiagnostic:
    contexte, n = rechercher_dans_chroma(etat["question"], TOP_K)
    log.info(f"ChromaDB → {n} chunks")
    return {**etat, "resultat_vectoriel": contexte or "Aucun extrait technique trouvé.", "nb_vector": n}


def noeud_skip_vector(etat: EtatDiagnostic) -> EtatDiagnostic:
    log.info("ChromaDB ignoré (non nécessaire pour ce type)")
    return {**etat, "resultat_vectoriel": "", "nb_vector": 0}


def condition_vector(etat: EtatDiagnostic) -> Literal["vector", "skip_vector"]:
    return "vector" if etat["besoin_vector"] else "skip_vector"


# ── Nœud 4 — Analyser (construction du prompt) ───────────────────
def noeud_analyser(etat: EtatDiagnostic) -> EtatDiagnostic:
    prompt = USER_TEMPLATE.format(
        resultat_sql=etat.get("resultat_sql", "Aucune donnée SQL"),
        resultat_vectoriel=etat.get("resultat_vectoriel", "Aucun extrait technique"),
        question=etat.get("question", "Quel est le diagnostic ?")
    )
    return {**etat, "prompt_utilisateur": prompt}


# ── Nœud 5 — LLM (Groq) ─────────────────────────────────────────
def noeud_llm(etat: EtatDiagnostic) -> EtatDiagnostic:
    if not GROQ_KEY:
        answer = _generate_demo_response(etat["question"], etat.get("resultat_sql", ""))
        return {**etat, "reponse_llm": answer}

    try:
        client = Groq(api_key=GROQ_KEY)
        completion = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": etat["prompt_utilisateur"]}
            ],
            temperature=0.0,
            max_completion_tokens=2048,
            top_p=0.95,
            stream=True,
            stop=None
        )

        reponse = ""
        for chunk in completion:
            content = chunk.choices[0].delta.content
            if content:
                reponse += content

        # Strip <think> blocks if present (Qwen3 reasoning)
        reponse = re.sub(r"<think>.*?</think>", "", reponse, flags=re.DOTALL).strip()
        log.info(f"LLM → {len(reponse)} caractères générés")
        return {**etat, "reponse_llm": reponse}

    except Exception as e:
        log.error(f"LLM Error: {e}")
        answer = _generate_demo_response(etat["question"], etat.get("resultat_sql", ""))
        return {**etat, "reponse_llm": answer}


# ── Construction du graphe LangGraph ──────────────────────────────
def construire_graphe():
    graphe = StateGraph(EtatDiagnostic)

    graphe.add_node("router",      noeud_router)
    graphe.add_node("sql",         noeud_sql)
    graphe.add_node("vector",      noeud_vector)
    graphe.add_node("skip_vector", noeud_skip_vector)
    graphe.add_node("analyser",    noeud_analyser)
    graphe.add_node("llm",         noeud_llm)

    graphe.set_entry_point("router")
    graphe.add_edge("router", "sql")

    graphe.add_conditional_edges(
        "sql",
        condition_vector,
        {
            "vector":      "vector",
            "skip_vector": "skip_vector"
        }
    )

    graphe.add_edge("vector",      "analyser")
    graphe.add_edge("skip_vector", "analyser")
    graphe.add_edge("analyser",    "llm")
    graphe.add_edge("llm",         END)

    return graphe.compile()


agent_truck = construire_graphe()
log.info("LangGraph Agent compilé: router → sql → [vector | skip_vector] → analyser → llm")


def poser_question(question: str) -> dict:
    """Interface principale — invoque le pipeline LangGraph complet."""
    etat_initial: EtatDiagnostic = {
        "question":           question,
        "type_requete":       "",
        "besoin_vector":      False,
        "resultat_sql":       "",
        "resultat_vectoriel": "",
        "prompt_utilisateur": "",
        "reponse_llm":        "",
        "nb_sql":             0,
        "nb_vector":          0,
    }
    return agent_truck.invoke(etat_initial)

def _generate_demo_response(question: str, context: str) -> str:
    """Structured response without LLM — based on SQL context analysis."""
    q = question.lower()
    lines = context.split("\n")

    # DTC detected
    dtc_match = re.search(r'\b([PCBU]\d{4})\b', question, re.IGNORECASE)
    if dtc_match:
        code = dtc_match.group(1).upper()
        for line in lines:
            if f"Code: {code}" in line:
                parts = dict(p.split(": ", 1) for p in line.replace("[DTC] ", "").split(" | ") if ": " in p)
                return (f"**🔧 Diagnostic DTC : {code}**\n\n"
                       f"- **Symptôme** : {parts.get('Symptôme','N/A')}\n"
                       f"- **Système** : {parts.get('Système','N/A')}\n"
                       f"- **Pièce** : {parts.get('Pièce','N/A')}\n"
                       f"- **Gravité** : {parts.get('Gravité','N/A')}\n\n"
                       f"⚠️ Action recommandée : Inspecter le composant indiqué et consulter un technicien agréé Volvo.")

    # Stats
    if any(w in q for w in ["combien","taux","pourcentage","statistique"]):
        for line in lines:
            if "FLEET_STATS" in line and "enregistrements" in line:
                return (f"**📊 Statistiques de la flotte**\n\n{context[:600]}\n\n"
                       f"⚠️ Action recommandée : Prioriser les véhicules avec score_predictif > 0.8 pour maintenance immédiate.")

    # Vehicle
    v_match = re.search(r'V(\d{4})', question, re.IGNORECASE)
    if v_match:
        vid = f"V{v_match.group(1)}"
        for line in lines:
            if f"Véhicule {vid}" in line:
                return (f"**🚛 Rapport Véhicule {vid}**\n\n```\n{line}\n```\n\n"
                       f"⚠️ Action recommandée : Vérifier le score prédictif et l'état des freins avant toute mise en circulation.")

    # Default
    return (f"**🤖 TruckMind — Mode Démo**\n\n"
           f"Données récupérées depuis la base SQLite :\n\n"
           f"```\n{context[:400]}\n```\n\n"
           f"⚠️ Action recommandée : Configurez GROQ_API_KEY pour des réponses complètes du LLM.\n\n"
           f"*Système opérationnel — RAG fonctionnel*")


# ═══════════════════════════════════════════════════════════════════
# ROUTES API
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM knowledge")
        nb_dtc = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM maintenance")
        nb_maint = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM thresholds")
        nb_thresh = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM maintenance_alerts")
        nb_alerts = cur.fetchone()[0]

        # Check if DB has data
        has_data = nb_dtc > 0 and nb_maint > 0

        return jsonify({
            "ready": has_data,
            "db_path": DB_PATH,
            "stats": {
                "dtc_codes": nb_dtc,
                "maintenance_records": nb_maint,
                "thresholds": nb_thresh,
                "alerts": nb_alerts
            },
            "llm": {
                "model": LLM_MODEL,
                "api_configured": bool(GROQ_KEY),
                "mode": "groq" if GROQ_KEY else "demo"
            },
            "version": "3.0.0",
            "pipeline": "langgraph",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"ready": False, "error": str(e), "db_path": DB_PATH}), 503

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Question vide"}), 400

    t0 = time.time()
    try:
        etat_final = poser_question(question)
        total_ms = int((time.time() - t0) * 1000)

        sql_ctx = etat_final.get("resultat_sql", "")
        return jsonify({
            "answer": etat_final["reponse_llm"],
            "type_requete": etat_final["type_requete"],
            "sources": {
                "sql_results": etat_final.get("nb_sql", 0),
                "vector_results": etat_final.get("nb_vector", 0),
                "sql_preview": sql_ctx[:300] + "..." if len(sql_ctx) > 300 else sql_ctx
            },
            "meta": {
                "model": LLM_MODEL,
                "total_ms": total_ms,
                "mode": "groq" if GROQ_KEY else "demo",
                "pipeline": "langgraph"
            }
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        log.error(f"Chat error: {e}", exc_info=True)
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500

@app.route("/api/fleet/stats")
def api_fleet_stats():
    try:
        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT
                COUNT(*) as total,
                ROUND(AVG(score_predictif),4) as avg_score,
                ROUND(MIN(score_predictif),4) as min_score,
                ROUND(MAX(score_predictif),4) as max_score,
                COUNT(CASE WHEN score_predictif > 0.8 THEN 1 END) as nb_critique,
                COUNT(CASE WHEN score_predictif > 0.5 AND score_predictif <= 0.8 THEN 1 END) as nb_eleve,
                COUNT(CASE WHEN score_predictif > 0.2 AND score_predictif <= 0.5 THEN 1 END) as nb_modere,
                COUNT(CASE WHEN score_predictif <= 0.2 THEN 1 END) as nb_faible,
                COUNT(CASE WHEN anomalie_detectee = 1 THEN 1 END) as nb_anomalies,
                COUNT(CASE WHEN entretien_necessaire = 1 THEN 1 END) as nb_entretien,
                ROUND(AVG(qualite_huile),2) as avg_huile,
                ROUND(AVG(temperature_moteur),2) as avg_temp,
                ROUND(AVG(pression_pneus),2) as avg_pression,
                ROUND(AVG(consommation_carburant),2) as avg_carburant
            FROM maintenance
        """)
        stats = dict(cur.fetchone())

        cur.execute("""
            SELECT etat_freins, COUNT(*) as nb
            FROM maintenance GROUP BY etat_freins ORDER BY nb DESC
        """)
        freins = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute("""
            SELECT action, COUNT(*) as nb
            FROM maintenance GROUP BY action ORDER BY nb DESC LIMIT 5
        """)
        entretiens = [{"type": r[0], "nb": r[1]} for r in cur.fetchall()]

        cur.execute("""
            SELECT t.lampe, COUNT(*) as nb
            FROM maintenance_alerts ma
            JOIN thresholds t ON ma.threshold_id = t.id
            GROUP BY t.lampe
        """)
        alertes = {row[0]: row[1] for row in cur.fetchall()}

        return jsonify({
            "global": stats,
            "freins": freins,
            "entretiens": entretiens,
            "alertes": alertes
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/fleet/alerts")
def api_fleet_alerts():
    try:
        db = get_db()
        cur = db.cursor()
        lampe = request.args.get("lampe", "ROUGE").upper()
        limit = min(int(request.args.get("limit", 20)), 100)

        cur.execute("""
            SELECT m.vehicule_id, m.date, t.parametre, t.lampe,
                   ma.valeur_mesuree, ma.depassement, t.action, t.unite,
                   m.score_predictif, m.etat_freins
            FROM maintenance_alerts ma
            JOIN maintenance  m ON ma.maintenance_id = m.id
            JOIN thresholds   t ON ma.threshold_id   = t.id
            WHERE t.lampe = ?
            ORDER BY m.score_predictif DESC, ma.id DESC
            LIMIT ?
        """, (lampe, limit))

        alerts = [dict(row) for row in cur.fetchall()]
        return jsonify({"alerts": alerts, "count": len(alerts), "lampe": lampe})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/vehicle/<vehicule_id>")
def api_vehicle(vehicule_id: str):
    try:
        db = get_db()
        cur = db.cursor()

        # Normalize ID
        if vehicule_id.isdigit():
            vehicule_id = f"V{int(vehicule_id):04d}"
        elif not vehicule_id.upper().startswith("V"):
            vehicule_id = f"V{int(vehicule_id):04d}"

        cur.execute("""
            SELECT m.id, m.vehicule_id, m.date, m.action, m.etat_freins, m.dtc,
                   m.anomalie_detectee, m.entretien_necessaire, m.score_predictif,
                   m.temperature_moteur, m.pression_pneus, m.qualite_huile,
                   m.etat_batterie, m.consommation_carburant, m.niveaux_vibration,
                   k.symptome, k.systeme, k.gravite
            FROM maintenance m
            LEFT JOIN knowledge k ON m.dtc = k.dtc
            WHERE m.vehicule_id = ?
            ORDER BY m.date DESC LIMIT 10
        """, (vehicule_id,))
        rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            return jsonify({"error": f"Véhicule {vehicule_id} introuvable"}), 404

        # Compute risk level
        for r in rows:
            s = r.get("score_predictif") or 0
            r["niveau_risque"] = ("CRITIQUE" if s > 0.8 else
                                  "ÉLEVÉ"    if s > 0.5 else
                                  "MODÉRÉ"   if s > 0.2 else "FAIBLE")

        return jsonify({
            "vehicule_id": vehicule_id,
            "nb_interventions": len(rows),
            "interventions": rows,
            "latest": rows[0] if rows else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/dtc/<code>")
def api_dtc(code: str):
    try:
        db = get_db()
        cur = db.cursor()
        code = code.upper()

        cur.execute("SELECT * FROM knowledge WHERE dtc = ?", (code,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": f"Code DTC {code} introuvable"}), 404

        dtc_data = dict(row)

        # Recent occurrences
        cur.execute("""
            SELECT vehicule_id, date, action, etat_freins, score_predictif
            FROM maintenance WHERE dtc = ?
            ORDER BY date DESC LIMIT 5
        """, (code,))
        occurrences = [dict(r) for r in cur.fetchall()]

        return jsonify({
            "dtc": dtc_data,
            "occurrences": occurrences,
            "nb_occurrences": len(occurrences)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/thresholds")
def api_thresholds():
    try:
        db = get_db()
        cur = db.cursor()
        lampe = request.args.get("lampe")
        if lampe:
            cur.execute("SELECT * FROM thresholds WHERE lampe = ? ORDER BY parametre", (lampe.upper(),))
        else:
            cur.execute("SELECT * FROM thresholds ORDER BY parametre, niveau_alerte")
        return jsonify({"thresholds": [dict(r) for r in cur.fetchall()]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/knowledge/search")
def api_knowledge_search():
    try:
        q = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 10)), 50)
        if not q:
            return jsonify({"error": "Paramètre 'q' requis"}), 400

        db = get_db()
        cur = db.cursor()

        # Try exact DTC match first
        cur.execute("SELECT * FROM knowledge WHERE dtc = ?", (q.upper(),))
        exact = cur.fetchone()
        if exact:
            return jsonify({"results": [dict(exact)], "type": "exact"})

        # Full-text search
        cur.execute("""
            SELECT * FROM knowledge
            WHERE dtc LIKE ? OR symptome LIKE ? OR systeme LIKE ? OR piece LIKE ?
            LIMIT ?
        """, (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit))
        results = [dict(r) for r in cur.fetchall()]
        return jsonify({"results": results, "count": len(results), "type": "search"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/fleet/top-risk")
def api_top_risk():
    try:
        db = get_db()
        cur = db.cursor()
        limit = min(int(request.args.get("limit", 10)), 50)

        cur.execute("""
            SELECT vehicule_id,
                   MAX(score_predictif) as score_max,
                   COUNT(*) as nb_interventions,
                   MAX(date) as derniere_intervention,
                   GROUP_CONCAT(DISTINCT etat_freins) as etats_freins,
                   AVG(qualite_huile) as avg_huile,
                   COUNT(CASE WHEN anomalie_detectee=1 THEN 1 END) as nb_anomalies
            FROM maintenance
            GROUP BY vehicule_id
            ORDER BY score_max DESC
            LIMIT ?
        """, (limit,))

        vehicles = []
        for r in cur.fetchall():
            row = dict(r)
            s = row["score_max"] or 0
            row["niveau_risque"] = ("CRITIQUE" if s > 0.8 else
                                    "ÉLEVÉ"    if s > 0.5 else
                                    "MODÉRÉ"   if s > 0.2 else "FAIBLE")
            vehicles.append(row)
        return jsonify({"vehicles": vehicles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ═══════════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Route introuvable", "code": 404}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Erreur serveur interne", "code": 500}), 500


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    port = int(os.environ.get("PORT", 5000))
    debug = "--debug" in sys.argv or os.environ.get("FLASK_DEBUG", "0") == "1"

    # Initialize ChromaDB pipeline at startup
    log.info("Initialisation du pipeline ChromaDB...")
    init_chroma_pipeline()

    print(f"""
======================================================
  🚛 TruckMind Backend v3.0 (LangGraph)               
  Auteure : AFFAKI Aya — EST Tétouan — IA DUT         
======================================================
  DB Path : {DB_PATH[:45]:<45} 
  LLM     : {LLM_MODEL:<45} 
  Mode    : {'GROQ API' if GROQ_KEY else 'DÉMO (sans clé API)':<45} 
  Pipeline: {'LangGraph (Router->SQL->Vector->LLM)':<45} 
  Port    : {port:<45} 
======================================================

  -> http://localhost:{port}/
  -> API : http://localhost:{port}/api/status
""".encode('utf-8', 'ignore').decode('utf-8'))

    app.run(host="0.0.0.0", port=port, debug=debug)