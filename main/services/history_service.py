"""
truck_memory.py — Gestionnaire de Mémoire TruckMind
=====================================================
Module centralisé pour la persistance et l'analyse
de l'historique des alertes et notifications.

Fonctions exposées :
  get_truck_history()          → Liste complète (historique permanent)
  save_entry(entry)            → Ajouter une entrée (permanent + RAM)
  get_last_entry()             → Dernière entrée permanente
  get_entries_by_severite()    → Filtrer par CRITIQUE / ATTENTION / NORMAL (depuis RAM)
  get_stats_summary()          → Statistiques pour le Dashboard (depuis RAM)
  get_recent_alerts(n)         → N dernières alertes réelles (depuis RAM)
  purge_old_entries(max_keep)  → Limiter la taille du fichier permanent (optionnel)
  purge_old_notifications()    → Limiter la taille des notifications RAM
  sync_reset_memory()          → Réinitialiser UNIQUEMENT les données temporaires (RAM + LangGraph)
  clear_notifications_ram()    → Vider les notifications RAM (utilisé au début d'un trajet)
"""

import json
import os
import threading
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(_ENV_PATH)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ══════════════════════════════════════════════════════════════════
# CHEMINS DES FICHIERS
# ══════════════════════════════════════════════════════════════════
# Mémoire long terme (données système uniquement) – NE JAMAIS VIDER
HISTORY_PATH = os.environ.get(
    "TRUCK_HISTORY_PATH",
    os.path.join(BASE_DIR, "truck_history.json")
)

# Mémoire court terme (RAM) - notifications temporaires
NOTIFICATIONS_RAM_PATH = os.environ.get(
    "NOTIFICATIONS_RAM_PATH",
    os.path.join(BASE_DIR, "notifications_ram.json")
)

# ══════════════════════════════════════════════════════════════════
# VERROU THREAD-SAFETY
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════
# LECTURE
# ══════════════════════════════════════════════════════════════════

def get_truck_history() -> List[dict]:
    """Retourne l'historique système complet (données capteurs uniquement). Liste vide si fichier absent."""
    if not os.path.exists(HISTORY_PATH):
        return []
    with _lock:
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []


def get_notifications_ram() -> List[dict]:
    """Retourne les notifications temporaires (RAM). Liste vide si fichier absent."""
    if not os.path.exists(NOTIFICATIONS_RAM_PATH):
        return []
    with _lock:
        try:
            with open(NOTIFICATIONS_RAM_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []


def get_last_entry() -> Optional[dict]:
    """Retourne la dernière entrée système sauvegardée, ou None."""
    history = get_truck_history()
    return history[-1] if history else None


def get_last_notification() -> Optional[dict]:
    """Retourne la dernière notification sauvegardée, ou None."""
    notifications = get_notifications_ram()
    return notifications[-1] if notifications else None


def get_recent_alerts(n: int = 10) -> List[dict]:
    """
    Retourne les N dernières notifications qui contiennent
    au moins une alerte ROUGE ou JAUNE (depuis la RAM).
    """
    notifications = get_notifications_ram()
    alertes_reelles = [
        e for e in notifications
        if e.get("severite") in ("CRITIQUE", "ATTENTION")
    ]
    return alertes_reelles[-n:]


def get_entries_by_severite(severite: str) -> List[dict]:
    """
    Filtre les notifications par niveau de sévérité.
    severite : "CRITIQUE" | "ATTENTION" | "NORMAL"
    """
    return [
        e for e in get_notifications_ram()
        if e.get("severite", "").upper() == severite.upper()
    ]


# ══════════════════════════════════════════════════════════════════
# ÉCRITURE
# ══════════════════════════════════════════════════════════════════

def save_entry(entry: dict) -> bool:
    """
    Ajoute une entrée à l'historique de façon thread-safe.
    Sépare les données système (long terme) des notifications (court terme).
    Retourne True si succès, False sinon.
    """
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with _lock:
        try:
            # Numéro de cycle auto si absent
            if "cycle" not in entry:
                history = get_truck_history()
                entry["cycle"] = len(history) + 1

            # Timestamp auto si absent
            if "timestamp" not in entry or not entry["timestamp"]:
                entry["timestamp"] = datetime.now().isoformat()

            # Sauvegarder les données système (long terme) – PERMANENT
            system_entry = {
                "cycle": entry.get("cycle"),
                "timestamp": entry.get("timestamp"),
                "capteurs": entry.get("capteurs")
            }
            
            history = []
            if os.path.exists(HISTORY_PATH):
                with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                    history = json.load(f)
            
            history.append(system_entry)
            with open(HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            # Sauvegarder les notifications (court terme - RAM)
            notification_entry = {
                "cycle": entry.get("cycle"),
                "timestamp": entry.get("timestamp"),
                "severite": entry.get("severite"),
                "statut_final": entry.get("statut_final"),
                "vitesse_max_kmh": entry.get("vitesse_max_kmh"),
                "action_vitesse": entry.get("action_vitesse"),
                "titre": entry.get("titre"),
                "alertes": entry.get("alertes"),
                "actions": entry.get("actions"),
                "notification": entry.get("notification"),
                "validation_status": entry.get("validation_status")
            }
            
            notifications = []
            if os.path.exists(NOTIFICATIONS_RAM_PATH):
                with open(NOTIFICATIONS_RAM_PATH, "r", encoding="utf-8") as f:
                    notifications = json.load(f)
            
            notifications.append(notification_entry)
            with open(NOTIFICATIONS_RAM_PATH, "w", encoding="utf-8") as f:
                json.dump(notifications, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"[TruckMemory] Erreur save_entry: {e}")
            return False


def clear_notifications_ram() -> bool:
    """
    Vide les notifications RAM (mémoire court terme).
    Retourne True si succès.
    Utilisé au début d'un nouveau trajet et à l'arrêt du serveur.
    """
    with _lock:
        try:    
            with open(NOTIFICATIONS_RAM_PATH, "w", encoding="utf-8") as f:
                json.dump([], f)
            return True
        except Exception as e:
            print(f"[TruckMemory] Erreur clear_notifications_ram: {e}")
            return False


def purge_old_entries(max_keep: int = 200) -> int:
    """
    Garde uniquement les `max_keep` entrées système les plus récentes.
    Retourne le nombre d'entrées supprimées.
    À n'utiliser que si l'utilisateur le souhaite explicitement.
    """
    with _lock:
        try:
            if not os.path.exists(HISTORY_PATH):
                return 0
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)

            if len(history) <= max_keep:
                return 0

            supprimees = len(history) - max_keep
            history    = history[-max_keep:]

            with open(HISTORY_PATH, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            print(f"[TruckMemory] Purge système : {supprimees} entrée(s) supprimée(s)")
            return supprimees
        except Exception as e:
            print(f"[TruckMemory] Erreur purge: {e}")
            return 0


def purge_old_notifications(max_keep: int = 50) -> int:
    """
    Garde uniquement les `max_keep` notifications les plus récentes (RAM).
    Retourne le nombre d'entrées supprimées.
    """
    with _lock:
        try:
            if not os.path.exists(NOTIFICATIONS_RAM_PATH):
                return 0
            with open(NOTIFICATIONS_RAM_PATH, "r", encoding="utf-8") as f:
                notifications = json.load(f)

            if len(notifications) <= max_keep:
                return 0

            supprimees = len(notifications) - max_keep
            notifications = notifications[-max_keep:]

            with open(NOTIFICATIONS_RAM_PATH, "w", encoding="utf-8") as f:
                json.dump(notifications, f, ensure_ascii=False, indent=2)

            print(f"[TruckMemory] Purge notifications RAM : {supprimees} entrée(s) supprimée(s)")
            return supprimees
        except Exception as e:
            print(f"[TruckMemory] Erreur purge notifications: {e}")
            return 0


# ══════════════════════════════════════════════════════════════════
# SYNCHRONISATION AVEC LA MÉMOIRE LANGGRAPH (Cellule 11)
# ══════════════════════════════════════════════════════════════════

def sync_reset_memory() -> bool:
    """
    Réinitialise UNIQUEMENT les données temporaires :
      1. Les notifications RAM (notifications_ram.json)
      2. La mémoire persistante de la Cellule 11
         (_alertes_compteur + _historique_valeurs)

    L'historique permanent (truck_history.json) n'est PAS touché.
    À appeler au début de chaque nouveau trajet.
    Retourne True si les opérations ont réussi.
    """
    ram_ok = clear_notifications_ram()

    # Import tardif pour éviter les imports circulaires
    try:
        from main.services.notification_service import reset_memory
        reset_memory()
        langgraph_ok = True
    except ImportError:
        try:
            # Fallback : module dans le même dossier
            from notification_service import reset_memory
            reset_memory()
            langgraph_ok = True
        except ImportError:
            print("[TruckMemory] ⚠️  reset_memory() non trouvé — mémoire LangGraph non réinitialisée")
            langgraph_ok = False

    print(f"[TruckMemory] sync_reset_memory → RAM={'✅' if ram_ok else '❌'} | LangGraph={'✅' if langgraph_ok else '⚠️'} (historique permanent conservé)")
    return ram_ok and langgraph_ok


# ══════════════════════════════════════════════════════════════════
# STATISTIQUES POUR LE DASHBOARD
# ══════════════════════════════════════════════════════════════════

def get_stats_summary() -> dict:
    """
    Calcule les statistiques globales à partir des notifications RAM.
    Utilisé par /api/fleet/stats et le Dashboard.

    Retourne :
    {
        "total_cycles"       : int,
        "total_alertes"      : int,   ← CRITIQUE + ATTENTION
        "critiques"          : int,
        "attentions"         : int,
        "normaux"            : int,
        "arrets_immediats"   : int,
        "reductions_vitesse" : int,
        "validation_rate"    : float, ← % notifications valides
        "last_timestamp"     : str | None,
        "capteurs_touches"   : dict,  ← {type: count}
        "alertes_recentes"   : list,  ← 5 dernières
    }
    """
    notifications = get_notifications_ram()

    if not notifications:
        return {
            "total_cycles": 0,
            "total_alertes": 0,
            "critiques": 0,
            "attentions": 0,
            "normaux": 0,
            "arrets_immediats": 0,
            "reductions_vitesse": 0,
            "validation_rate": 0.0,
            "last_timestamp": None,
            "capteurs_touches": {},
            "alertes_recentes": [],
        }

    critiques   = sum(1 for e in notifications if e.get("severite") == "CRITIQUE")
    attentions  = sum(1 for e in notifications if e.get("severite") == "ATTENTION")
    normaux     = sum(1 for e in notifications if e.get("severite") == "NORMAL")
    arrets      = sum(1 for e in notifications if e.get("statut_final") == "ARRET IMMEDIAT")
    reductions  = sum(1 for e in notifications if e.get("statut_final") == "REDUIRE VITESSE")

    # Taux de validation des notifications
    avec_validation = [
        e for e in notifications
        if e.get("validation_status") and isinstance(e["validation_status"], dict)
    ]
    if avec_validation:
        valides         = sum(1 for e in avec_validation if e["validation_status"].get("globally_valid"))
        validation_rate = round(valides / len(avec_validation) * 100, 1)
    else:
        validation_rate = 0.0

    # Comptage des types de capteurs touchés
    capteurs_touches: dict = {}
    MOTS_CAPTEURS = {
        "température": "temperature",
        "temperature": "temperature",
        "pression":    "pression_pneus",
        "frein":       "freins",
        "batterie":    "batterie",
        "vibration":   "vibrations",
        "consommation":"consommation",
        "surcharge":   "surcharge",
    }

    for entry in notifications:
        for alerte in entry.get("alertes", []):
            al = alerte.lower()
            for mot, cle in MOTS_CAPTEURS.items():
                if mot in al and ("[rouge]" in al or "[jaune]" in al):
                    capteurs_touches[cle] = capteurs_touches.get(cle, 0) + 1
                    break  # Un seul type par alerte

    # 5 dernières alertes réelles (pour le widget Dashboard)
    alertes_recentes = []
    for entry in reversed(notifications):
        if entry.get("severite") in ("CRITIQUE", "ATTENTION"):
            alertes_recentes.append({
                "cycle":     entry.get("cycle"),
                "timestamp": entry.get("timestamp"),
                "titre":     entry.get("titre", ""),
                "severite":  entry.get("severite"),
                "statut":    entry.get("statut_final"),
            })
        if len(alertes_recentes) >= 5:
            break

    last_ts = notifications[-1].get("timestamp") if notifications else None

    return {
        "total_cycles":       len(notifications),
        "total_alertes":      critiques + attentions,
        "critiques":          critiques,
        "attentions":         attentions,
        "normaux":            normaux,
        "arrets_immediats":   arrets,
        "reductions_vitesse": reductions,
        "validation_rate":    validation_rate,
        "last_timestamp":     last_ts,
        "capteurs_touches":   capteurs_touches,
        "alertes_recentes":   alertes_recentes,
    }