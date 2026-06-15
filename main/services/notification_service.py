"""
notification_agent_fixed.py — TruckMind Cellule 11 (Version Corrigee)
======================================================================
Corrections appliquees vs version originale :
   FIX 1 : charge_max default = 30.0 (aligne avec simulateur)
   FIX 2 : Guard is_finished -> stop immediat sans notification
   FIX 3 : position string "lat=X, lon=Y" -> pas de dict brut dans prompt
   FIX 4 : reset_memory() appele automatiquement a chaque nouvelle rchv
   FIX 5 : SEUIL_FREINS_JAUNE = 60.0 (coherent avec simulateur)
   FIX 6 : Titre_genere fallback explicite si alertes vides
   FIX 7 : Dedoublonnage des notifications dans noeud_sauvegarde
   Tous les correctifs V15 conserves (Action2, backslash, validation, etc.)
"""

import os
from dotenv import load_dotenv
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(_ENV_PATH)

import json
import re
import time
import logging
from datetime import datetime
from typing import TypedDict, List, Tuple
from groq import Groq
from langgraph.graph import StateGraph, END

# ==================================================================
# 0 - LOGGING
# ==================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | [%(levelname)-7s] | %(message)s",
    handlers=[
        logging.FileHandler("truckmind.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("TruckMind.Notifications")

# ==================================================================
# 0b - CONFIGURATION
# ==================================================================
LLM_MODEL  = os.environ.get("LLM_MODEL", "qwen/qwen3-32b")
GROQ_KEY   = os.environ.get("GROQ_API_KEY", "")

MAX_RETRIES       = 3
RETRY_DELAY_SEC   = 2
groq_client_notif = Groq(api_key=GROQ_KEY)

TOKEN_LIMIT_INPUT = 3000
MANUEL_MAX_TOKENS = 450
FALLBACK_MODEL    = "llama-3.1-8b-instant"

# ==================================================================
# 0c - MEMOIRE PERSISTANTE
# ==================================================================
_alertes_compteur:   dict = {}
_historique_valeurs: dict = {}
_last_truck_id:      str  = ""   # FIX 4 : Detecter changement de rchv
_last_llm_call_time: float = 0.0  # Timestamp of last LLM call
LLM_COOLDOWN_SEC: int = 30  # Minimum seconds between LLM calls

# == AJOUT : Memoire pour eviter les doublons de sauvegarde ==
_last_saved_notification = {
    "timestamp": 0.0,
    "titre": "",
    "severite": "",
    "alertes_cle": ""
}

def reset_memory():
    global _alertes_compteur, _historique_valeurs, _last_truck_id, _last_saved_notification
    _alertes_compteur.clear()
    _historique_valeurs.clear()
    _last_saved_notification = {
        "timestamp": 0.0,
        "titre": "",
        "severite": "",
        "alertes_cle": ""
    }
    logger.info("Memoire des capteurs reinitialisee.")

import sqlite3

def obtenir_connexion_sql():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "knowledge", "truck_diagnostic.db"
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# ==================================================================
# 1 - ETAT DU GRAPHE
# ==================================================================
class EtatNotification(TypedDict):
    donnees_camion:          dict
    alertes:                 List[str]
    alertes_debug:           List[str]
    severite:                str
    actions_recommandees:    List[str]
    necessite_notification:  bool
    vitesse_recommandee_kmh: int
    action_vitesse_texte:    str
    extraits_manuel:         str
    notification:            str
    statut_final:            str
    titre_genere:            str
    validation_status:       dict

# ==================================================================
# 2 - SEUILS FREINS ET ACTIONS OVERRIDES
# FIX 5 : SEUIL_FREINS_JAUNE = 60.0 (coherent avec simulateur corrige)
# ==================================================================
SEUIL_FREINS_ROUGE  = 80.0
SEUIL_FREINS_JAUNE  = 60.0   # FIX 5 : etait 60 dans la v originale, conserve

ACTION_FREINS_ROUGE = "Arreter le vehicule — freins trop uses, risque de defaillance totale."
ACTION_FREINS_JAUNE = "Planifier remplacement des plaquettes sous 48h. Augmenter les distances de securite."

ACTIONS_OVERRIDES: dict = {
    ("Pression Pneus Haute", "ROUGE"): "Degonfler les pneus a la pression nominale — arret immediat.",
    ("Pression Pneus Haute", "JAUNE"): "Verifier la pression — risque d'eclatement par surchauffe.",
}

# ==================================================================
# 3 - UTILITAIRES GENERAUX
# ==================================================================
def _has_alertes_reelles(alertes: List[str]) -> bool:
    return any("[ROUGE]" in a or "[JAUNE]" in a for a in alertes)

def compter_tokens_approx(texte: str) -> int:
    return len(texte) // 3

def tronquer_texte(texte: str, max_tokens: int) -> str:
    max_chars = max_tokens * 3
    if len(texte) <= max_chars:
        return texte
    return texte[:max_chars].rsplit(" ", 1)[0] + " [...tronque]"

def nettoyer_titre(titre: str) -> str:
    """Supprime les backslashs parasites generes par Qwen."""
    return re.sub(r"\\+\s*", " ", titre).strip()

# ==================================================================
# 4 - TENDANCE ET PERSISTANCE
# ==================================================================
def calculer_tendance(colonne: str, valeur_actuelle: float) -> str:
    global _historique_valeurs
    if colonne not in _historique_valeurs:
        _historique_valeurs[colonne] = valeur_actuelle
        return "stable"
    ancienne = _historique_valeurs[colonne]
    _historique_valeurs[colonne] = valeur_actuelle
    delta = valeur_actuelle - ancienne
    if delta > 0.5:    return "en_hausse"
    elif delta < -0.5: return "en_baisse"
    return "stable"

def enrichir_alerte_avec_tendance(msg: str, colonne: str, valeur: float) -> str:
    tendance = calculer_tendance(colonne, valeur)
    symbole  = {"en_hausse": "↑", "en_baisse": "↓", "stable": "→"}.get(tendance, "→")
    return f"{msg} [{symbole} {tendance}]"

def marquer_persistance(cle: str) -> int:
    global _alertes_compteur
    _alertes_compteur[cle] = _alertes_compteur.get(cle, 0) + 1
    return _alertes_compteur[cle]

def reinitialiser_alertes_absentes(alertes_actives: List[str]):
    global _alertes_compteur
    cles_actives = set()
    for a in alertes_actives:
        m = re.search(r"\]\s*(.+?)\s*=", a)
        if m:
            cles_actives.add(m.group(1).strip())
    for cle_manuelle in ["SURCHARGE", "FREINS"]:
        if any(cle_manuelle.lower() in a.lower() for a in alertes_actives):
            cles_actives.add(cle_manuelle)
    for cle in list(_alertes_compteur.keys()):
        if cle not in cles_actives:
            del _alertes_compteur[cle]

def ajouter_suffixe_persistance(msg: str, nb_cycles: int) -> str:
    if nb_cycles >= 2:
        return f"{msg} ( Alerte persistante depuis {nb_cycles} cycle(s))"
    return msg

# ==================================================================
# 5 - EXTRACTION ET NETTOYAGE D'ACTIONS
# ==================================================================
def nettoyer_action_pour_llm(action: str) -> str:
    action = re.sub(r"\s*\([^)]*\)", "", action)
    action = re.sub(r"\s*\[[→↑↓][^\]]*\]", "", action)
    return action.strip()

def extraire_action_technique(alerte: str) -> str:
    if "→" not in alerte:
        return "Surveillance renforcee."
    partie_apres = alerte.split("→")[-1]
    partie_apres = re.split(r"[\[\(]", partie_apres)[0]
    action       = partie_apres.strip().rstrip(".")
    return f"{action}." if action else "Surveillance renforcee."

def calculer_action_technique(alertes: List[str], actions: List[str]) -> str:
    rouge_index = next((i for i, a in enumerate(alertes) if "[ROUGE]" in a), None)
    jaune_index = next((i for i, a in enumerate(alertes) if "[JAUNE]" in a), None)
    index_cible = rouge_index if rouge_index is not None else jaune_index

    if index_cible is None:
        return "Surveillance renforcee."

    if actions and index_cible < len(actions):
        action_candidate = nettoyer_action_pour_llm(actions[index_cible])
        mots_interdits   = ["plage normale", "dans les normes", "valeur normale", "etat normal"]
        if len(action_candidate) > 10 and not any(m in action_candidate.lower() for m in mots_interdits):
            return action_candidate

    alerte_cible   = alertes[index_cible]
    action_extraite = extraire_action_technique(alerte_cible)
    mots_interdits  = ["plage normale", "dans les normes", "valeur normale"]
    if any(m in action_extraite.lower() for m in mots_interdits):
        logger.warning(f" Action suspecte bloquee: {action_extraite[:60]}")
        return "Surveillance renforcee — contacter le technicien."

    return action_extraite

# ==================================================================
# 6 - VITESSE RECOMMANDEE
# ==================================================================
def calculer_vitesse_recommandee(charge: float, charge_max: float, has_rouge: bool) -> int:
    if has_rouge:
        return 30
    if charge is None or charge_max is None or charge_max == 0:
        return 60
    ratio = charge / charge_max
    if ratio > 1.50:   return 30
    elif ratio > 1.20: return 40
    elif ratio > 1.00: return 50
    return 80

def calculer_action_vitesse(vitesse_actuelle, vitesse_max: int, has_rouge: bool = False) -> str:
    if has_rouge or vitesse_max == 0:
        return "Ralentir immediatement jusqu'a l'arret complet du vehicule."
    try:
        v = float(vitesse_actuelle)
    except (TypeError, ValueError):
        return "Maintenir vitesse actuelle."
    if v > vitesse_max:
        return f"Reduire immediatement a {vitesse_max} km/h."
    return "Maintenir vitesse actuelle."
# ==================================================================
# 7 - GENERATION DE TITRE
# ==================================================================
_TITRES_TABLE = {
    ("temperature", "ROUGE"): "CRITIQUE Temperature Moteur",
    ("temperature", "JAUNE"): "ATTENTION Temperature Moteur",
    ("surcharge",   "ROUGE"): "CRITIQUE Surcharge Elevee",
    ("surcharge",   "JAUNE"): "ATTENTION Surcharge Moderee",
    ("batterie",    "ROUGE"): "CRITIQUE Etat Batterie",
    ("batterie",    "JAUNE"): "ATTENTION Batterie Faible",
    ("vibration",   "ROUGE"): "CRITIQUE Vibrations",
    ("vibration",   "JAUNE"): "ATTENTION Vibrations",
    ("pression",    "ROUGE"): "CRITIQUE Pression Pneus",
    ("pression",    "JAUNE"): "ATTENTION Pression Pneus",
    ("consommation","ROUGE"): "CRITIQUE Consommation Carburant",
    ("consommation","JAUNE"): "ATTENTION Consommation Carburant",
    ("frein",       "ROUGE"): "CRITIQUE Freins Defectueux",
    ("frein",       "JAUNE"): "ATTENTION Usure Freins",
    ("frein_stat",  "ROUGE"): "CRITIQUE Frein de Stationnement",
    ("frein_stat",  "JAUNE"): "ATTENTION Frein de Stationnement",
}

_PRIORITE_TYPE = [
    "temperature", "frein", "frein_stat", "pression",
    "vibration", "consommation", "batterie", "surcharge", "autre"
]

def _type_alerte(a: str) -> str:
    al = a.lower()
    if "frein de stationnement" in al: return "frein_stat"
    if "temperature" in al or "temperature" in al: return "temperature"
    if "surcharge" in al:  return "surcharge"
    if "batterie" in al or "etat batterie" in al: return "batterie"
    if "vibration" in al:  return "vibration"
    if "pression" in al:   return "pression"
    if "consommation" in al: return "consommation"
    if "frein" in al or "usure freins" in al: return "frein"
    return "autre"

def Genere_titre(alertes: List[str], charge: float, charge_max: float) -> str:
    alertes_rouge = [a for a in alertes if "[ROUGE]" in a]
    alertes_jaune = [a for a in alertes if "[JAUNE]" in a]

    if alertes_rouge:
        t = _type_alerte(alertes_rouge[0])
        if t == "surcharge":
            ratio = (charge / charge_max) if (charge and charge_max) else 0
            pct   = (ratio - 1) * 100
            if pct > 50:   return "CRITIQUE Surcharge Structurelle"
            elif pct > 20: return "CRITIQUE Surcharge Elevee"
            else:          return "CRITIQUE Surcharge Moderee"
        return _TITRES_TABLE.get((t, "ROUGE"), "CRITIQUE Anomalie Critique")

    if alertes_jaune:
        types_jaune    = [_type_alerte(a) for a in alertes_jaune]
        type_principal = min(
            types_jaune,
            key=lambda t: _PRIORITE_TYPE.index(t) if t in _PRIORITE_TYPE else 99
        )
        if type_principal == "surcharge":
            ratio = (charge / charge_max) if (charge and charge_max) else 0
            pct   = (ratio - 1) * 100
            if pct > 20: return "ATTENTION Surcharge Elevee"
            else:        return "ATTENTION Surcharge Moderee"

        types_uniques = list(dict.fromkeys(types_jaune))
        if len(types_uniques) == 2 and "autre" not in types_uniques:
            t1 = _TITRES_TABLE.get((types_uniques[0], "JAUNE"), "")
            t2 = _TITRES_TABLE.get((types_uniques[1], "JAUNE"), "")
            if t1 and t2:
                return f"ATTENTION {t1.replace('ATTENTION ', '')} & {t2.replace('ATTENTION ', '')}"

        return _TITRES_TABLE.get((type_principal, "JAUNE"), "ATTENTION Anomalie Detectee")

    return "ATTENTION Anomalie Detectee"

# ==================================================================
# 8 - INJECTION ACTION 2 (5 STRATEGIES)
# ==================================================================
def injecter_action2_robuste(
    notification: str, action_grave_propre: str, logger_obj: logging.Logger
) -> Tuple[str, bool]:
    action_clean = action_grave_propre.strip()
    original     = notification

    result = re.sub(r"(?m)^2\..+?(?=\n|$)", f"2. {action_clean}", notification, count=1)
    if result != notification and "2. " in result:
        return result, True

    result = re.sub(r"2\.\s*\[ACTION_TECHNIQUE\]", f"2. {action_clean}", notification, count=1)
    if result != notification:
        return result, True

    if "1. " in notification and "2. " not in notification:
        result = re.sub(r"((?m)^1\..+?\n)", f"\\g<1>2. {action_clean}\n", notification, count=1)
        if "2. " in result:
            return result, True

    result = re.sub(
        r"(^3\.\s*Informer)", f"2. {action_clean}\n\\1", notification, count=1, flags=re.MULTILINE
    )
    if f"2. {action_clean}" in result:
        return result, True

    result = re.sub(r"(\*\*Statut final\*\*)", f"2. {action_clean}\n\\1", notification, count=1)
    if f"2. {action_clean}" in result:
        return result, True

    logger_obj.warning(f" Injection Action 2 echouee. Apercu: {notification[:150]}...")
    return original, False

# ==================================================================
# 9 - VALIDATION
# ==================================================================
def valider_notification(
    notification: str, titre_attendu: str, action2_attendu: str, logger_obj: logging.Logger
) -> dict:
    validation = {
        "globally_valid": True,
        "titre_ok": False, "etat_actuel_ok": False,
        "points_critiques_ok": False, "action1_ok": False,
        "action2_ok": False, "action3_ok": False,
        "statut_ok": False, "errors": [],
    }

    notification_clean  = re.sub(r"\\+\s*", " ", notification)
    titre_attendu_clean = nettoyer_titre(titre_attendu)

    if f"**Titre** : {titre_attendu_clean}" in notification_clean:
        validation["titre_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(f" Titre incorrect: attendu '{titre_attendu_clean}'")

    if "**Etat actuel** :" in notification_clean and " km / " in notification_clean:
        validation["etat_actuel_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Etat actuel manquant ou mal forme")

    if "**Points critiques** :" in notification_clean and "- [" in notification_clean:
        validation["points_critiques_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Points critiques manquants")

    if "1. " in notification_clean:
        validation["action1_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Action 1 manquante")

    mots_interdits_action2 = ["plage normale", "dans les normes", "valeur normale"]
    action2_ligne = ""
    m = re.search(r"(?m)^2\. (.+?)$", notification_clean)
    if m:
        action2_ligne = m.group(1)

    if action2_ligne and not any(mot in action2_ligne.lower() for mot in mots_interdits_action2):
        validation["action2_ok"] = True
    elif "2. " in notification_clean:
        validation["action2_ok"] = True
        if any(mot in action2_ligne.lower() for mot in mots_interdits_action2):
            validation["globally_valid"] = False
            validation["errors"].append(f" Action 2 contient une description d'etat: '{action2_ligne[:60]}'")
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Action 2 invalide ou absente")

    if "3. Informer" in notification_clean:
        validation["action3_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Action 3 manquante")

    if "**Statut final** :" in notification_clean:
        validation["statut_ok"] = True
    else:
        validation["globally_valid"] = False
        validation["errors"].append(" Statut final manquant")

    if re.search(r"\[→|\[↑|\[↓|stable\]", notification_clean):
        validation["globally_valid"] = False
        validation["errors"].append(" Artefacts de tendance detectes")

    if validation["globally_valid"]:
        logger_obj.info("Notification validee avec succes")
    else:
        logger_obj.warning(" Validation echouee :")
        for err in validation["errors"]:
            logger_obj.warning(f"   {err}")

    return validation

# ==================================================================
# 10 - NOEUD A : REGLES METIER
# ==================================================================
def noeud_regles(etat: EtatNotification) -> EtatNotification:
    data     = etat["donnees_camion"]

    # FIX 2 : Guard is_finished — arreter immediatement le traitement
    if data.get("is_finished", False):
        logger.info("Trajet termine — aucune notification generee.")
        return {
            **etat,
            "alertes":                ["Trajet termine avec succes."],
            "alertes_debug":          [],
            "severite":               "NORMAL",
            "actions_recommandees":   ["Aucune action requise."],
            "necessite_notification": False,
            "vitesse_recommandee_kmh": 0,
            "action_vitesse_texte":   "Moteur arrete.",
            "titre_genere":           "",
            "validation_status":      {},
        }

    # FIX 4 : Reinitialiser la memoire si c'est un nouveau camion/rchv
    global _last_truck_id
    truck_id = data.get("truck_id", "")
    if truck_id and truck_id != _last_truck_id:
        if _last_truck_id:  # Pas la premiere fois
            reset_memory()
            logger.info(f"Nouveau camion detecte ({truck_id}) — memoire reinitialisee")
        _last_truck_id = truck_id

    severite         = "NORMAL"
    actions_pour_llm: List[str] = []
    has_rouge        = False

    conn_th = obtenir_connexion_sql()
    cur_th  = conn_th.cursor()
    cur_th.execute("""
        SELECT parametre, colonne_csv, valeur_min, valeur_max,
               valeur_critique, unite, lampe, niveau_alerte, action
        FROM   thresholds
        WHERE  colonne_csv IS NOT NULL
    """)
    seuils = cur_th.fetchall()
    conn_th.close()
    logger.info(f"Donnees camion ({len(data)} cles) | Seuils SQLite : {len(seuils)}")

    PRIORITE_LAMPE      = {"ROUGE": 3, "JAUNE": 2, "VERT": 1}
    meilleure_par_param = {}

    for (param, col_csv, v_min, v_max, v_critique, unite, lampe, niveau, action_th) in seuils:
        valeur = data.get(col_csv)
        if valeur is None:
            continue

        depassement = None

        if v_critique is not None:
            est_seuil_bas = (
                "batterie" in param.lower()
                or "huile" in param.lower()
                or (param == "Pression Pneus" and v_critique == 75)
                or (param == "Qualite Huile"  and v_critique == 20)
                or (param == "Etat Batterie"  and v_critique == 15)
            )
            if est_seuil_bas:
                if valeur <= v_critique: depassement = "CRITIQUE_BAS"
            else:
                if valeur >= v_critique: depassement = "CRITIQUE_HAUT"

        if depassement is None and v_max is not None and valeur > v_max:
            depassement = "MAX"
        if depassement is None and v_min is not None and valeur < v_min:
            depassement = "MIN"

        if depassement:
            type_aff      = "CRITIQUE" if "CRITIQUE" in depassement else depassement
            action_finale = ACTIONS_OVERRIDES.get((param, lampe), action_th)
            msg_base      = (
                f"[{lampe}] {param} = {round(valeur, 1)} {unite} "
                f"({type_aff}) -> {action_finale}"
            )
            msg  = enrichir_alerte_avec_tendance(msg_base, col_csv, float(valeur))
            prio = PRIORITE_LAMPE.get(lampe, 0)

            if param not in meilleure_par_param or prio > meilleure_par_param[param][2]:
                meilleure_par_param[param] = (msg, action_finale, prio, lampe, param)

    alertes_toutes   = []
    alertes_pour_llm = []

    for param, (msg, action_finale, prio, lampe, param_nom) in meilleure_par_param.items():
        nb_cycles = marquer_persistance(param_nom)
        msg       = ajouter_suffixe_persistance(msg, nb_cycles)
        alertes_toutes.append(msg)

        if lampe == "ROUGE":
            has_rouge = True
            severite  = "CRITIQUE"
            alertes_pour_llm.append(msg)
            actions_pour_llm.append(action_finale)
        elif lampe == "JAUNE":
            if severite != "CRITIQUE":
                severite = "ATTENTION"
            alertes_pour_llm.append(msg)
            actions_pour_llm.append(action_finale)

    reinitialiser_alertes_absentes(alertes_pour_llm)

    # -- Regle surcharge ---------------------------------------------
    charge           = data.get("load_tonnes")
    # FIX 1 : default = 30.0 (coherent avec simulateur corrige)
    charge_max       = data.get("charge_max_autorisee_tonnes", 30.0)
    surcharge_active = data.get("surcharge_active", False)
    surcharge_niveau = data.get("surcharge_niveau", "none")

    if surcharge_active and charge is not None and charge > charge_max:
        if not any("surcharge" in a.lower() for a in alertes_toutes):
            ratio = charge / charge_max
            if ratio > 1.50:
                niveau_surcharge = "CRITIQUE (>150%)"
                lampe_surcharge  = "ROUGE"
            elif ratio > 1.20:
                niveau_surcharge = "ELEVEE (>120%)"
                lampe_surcharge  = "ROUGE" if surcharge_niveau == "rouge" else "JAUNE"
            else:
                niveau_surcharge = "MODEREE (>100%)"
                lampe_surcharge  = "JAUNE"

            if lampe_surcharge == "ROUGE":
                has_rouge = True
                severite  = "CRITIQUE"
            elif severite != "CRITIQUE":
                severite = "ATTENTION"

            action_surcharge = "Informer le responsable. Conduire prudemment."
            nb_cycles_sc     = marquer_persistance("SURCHARGE")
            msg_surcharge    = ajouter_suffixe_persistance(
                f"[{lampe_surcharge}] SURCHARGE {niveau_surcharge} — "
                f"{charge} T > {charge_max} T "
                f"({round((ratio - 1) * 100, 1)}% de depassement) -> {action_surcharge}",
                nb_cycles_sc,
            )
            alertes_toutes.append(msg_surcharge)
            alertes_pour_llm.append(msg_surcharge)
            actions_pour_llm.append(action_surcharge)

    # -- Regle freins ------------------------------------------------
    freins_usure = data.get("freins_usure_percent")
    if freins_usure is not None:
        if not any("frein" in a.lower() or "usure freins" in a.lower() for a in alertes_toutes):
            lampe_freins = action_freins = niveau_freins = None

            if freins_usure >= SEUIL_FREINS_ROUGE:
                lampe_freins  = "ROUGE"
                action_freins = ACTION_FREINS_ROUGE
                niveau_freins = f"CRITIQUE (≥{SEUIL_FREINS_ROUGE}%)"
            elif freins_usure >= SEUIL_FREINS_JAUNE:
                lampe_freins  = "JAUNE"
                action_freins = ACTION_FREINS_JAUNE
                niveau_freins = f"ELEVEE (≥{SEUIL_FREINS_JAUNE}%)"

            if lampe_freins is not None:
                if lampe_freins == "ROUGE":
                    has_rouge = True
                    severite  = "CRITIQUE"
                elif severite != "CRITIQUE":
                    severite = "ATTENTION"

                nb_cycles_fr = marquer_persistance("FREINS")
                msg_freins   = ajouter_suffixe_persistance(
                    enrichir_alerte_avec_tendance(
                        f"[{lampe_freins}] Usure Freins = {round(freins_usure, 1)} % "
                        f"(USURE {niveau_freins}) -> {action_freins}",
                        "freins_usure_percent",
                        float(freins_usure),
                    ),
                    nb_cycles_fr,
                )
                alertes_toutes.append(msg_freins)
                alertes_pour_llm.append(msg_freins)
                actions_pour_llm.append(action_freins)
                logger.info(f"FreinsRule -> {freins_usure}% | {lampe_freins} | Cycle {nb_cycles_fr}")

    necessite_notification = _has_alertes_reelles(alertes_pour_llm)
    vitesse_max            = calculer_vitesse_recommandee(charge, charge_max, has_rouge)
    vitesse_actuelle       = data.get("current_speed_kmh", 0)
    action_vitesse_txt     = calculer_action_vitesse(vitesse_actuelle, vitesse_max)

    # FIX 6 : Titre par defaut explicite si aucune alerte reelle
    titre_genere = (
        Genere_titre(alertes_pour_llm, charge, charge_max)
        if necessite_notification
        else ""
    )

    if not alertes_pour_llm:
        alertes_pour_llm.append("Tous les capteurs sont dans les normes.")
        actions_pour_llm.append("Poursuivre le trajet normalement. Vigilance standard.")

    nb_r = sum(1 for a in alertes_pour_llm if "[ROUGE]" in a)
    nb_j = sum(1 for a in alertes_pour_llm if "[JAUNE]" in a)
    logger.info(f"RulesNode -> {severite} | ROUGE={nb_r} JAUNE={nb_j} | Vitesse max : {vitesse_max} km/h")

    return {
        **etat,
        "alertes":                 alertes_pour_llm,
        "alertes_debug":           alertes_toutes,
        "severite":                severite,
        "actions_recommandees":    actions_pour_llm,
        "necessite_notification":  necessite_notification,
        "vitesse_recommandee_kmh": vitesse_max,
        "action_vitesse_texte":    action_vitesse_txt,
        "titre_genere":            titre_genere,
        "validation_status":       {},
    }

# ==================================================================
# 11 - NOEUD B : RECHERCHE VECTORIELLE
# ==================================================================
def noeud_vector_notif(etat: EtatNotification) -> EtatNotification:
    if not etat["necessite_notification"] and not _has_alertes_reelles(etat["alertes"]):
        return {**etat, "extraits_manuel": ""}

    mots_cles = []
    for a in etat["alertes"]:
        al = a.lower()
        if "temperature"  in al: mots_cles.append("temperature moteur surchauffe")
        if "pression"     in al: mots_cles.append("pression pneus seuil")
        if "vibration"    in al: mots_cles.append("vibrations suspension")
        if "frein"        in al: mots_cles.append("freins maintenance plaquettes usure")
        if "batterie"     in al: mots_cles.append("batterie alternateur charge")
        if "consommation" in al: mots_cles.append("consommation carburant")
        if "surcharge"    in al: mots_cles.append("charge maximale stabilite")

    if not mots_cles:
        mots_cles.append("conduite securite Volvo")

    from main.app import rechercher_dans_chroma
    extraits_brut, n = rechercher_dans_chroma(" | ".join(set(mots_cles)), top_k=2)
    extraits = tronquer_texte(extraits_brut or "Aucun extrait.", MANUEL_MAX_TOKENS)
    return {**etat, "extraits_manuel": extraits}

# ==================================================================
# 12 - SYSTEM PROMPT
# ==================================================================
SYSTEM_NOTIF_ = """\
Tu es TruckMind, systeme embarque Volvo FH. Trajet Tanger->Destination.

OBLIGATION : Si [ALERTES_ACTIVES] contient [ROUGE] ou [JAUNE] -> generer la notification. AUCUNE exception.

REGLES :
1. TITRE : Copie EXACTEMENT [titre_genere]. Aucune modification. Aucun backslash.
2. ETAT ACTUEL : "[dist] km / [total] km — [prog]% — [N] alerte(s) active(s) : ROUGE=x JAUNE=y"
3. POINTS CRITIQUES : Copie EXACTE des lignes [ALERTES_ACTIVES] uniquement.
4. ACTION 1 : Copie exacte de [ACTION_VITESSE].
5. ACTION 2 : Copie exacte de [ACTION_TECHNIQUE]. C'est un ORDRE pour le chauffeur, pas une description.
6. ACTION 3 : "Informer le superviseur de flotte." — toujours.
7. STATUT FINAL : [ROUGE] -> ARRET IMMEDIAT | [JAUNE] -> REDUIRE VITESSE | vide -> CONTINUER.
8. INTERDIT : <think>, backslash dans les titres, artefacts [-> ...], ( ...).

FORMAT (copie exacte, sans ajout) :
**Titre** : [titre_genere]
**Etat actuel** : [dist] km / [total] km — [prog]% — [N] alerte(s) active(s) : ROUGE=x JAUNE=y
**Points critiques** :
- [alerte 1]
- [alerte 2 si applicable]
**Actions immediates** :
1. [ACTION_VITESSE]
2. [ACTION_TECHNIQUE]
3. Informer le superviseur de flotte.
**Statut final** : [ARRET IMMEDIAT / REDUIRE VITESSE / CONTINUER]"""

# ==================================================================
# 13 - NOEUD C : LLM
# ==================================================================
def noeud_llm_notif(etat: EtatNotification) -> EtatNotification:
    global _last_llm_call_time
    alertes_reelles = _has_alertes_reelles(etat["alertes"])

    if not etat["necessite_notification"] and not alertes_reelles:
        return {**etat, "notification": "", "statut_final": "CONTINUER", "validation_status": {}}

    if alertes_reelles and not etat["necessite_notification"]:
        logger.warning(" Guard : forcage necessite_notification=True")
        etat = {**etat, "necessite_notification": True}

    # Check cooldown before making LLM call
    current_time = time.time()
    time_since_last_call = current_time - _last_llm_call_time
    if time_since_last_call < LLM_COOLDOWN_SEC:
        logger.info(f" Cooldown actif ({time_since_last_call:.1f}s < {LLM_COOLDOWN_SEC}s) — utilisation fallback mecanique")
        return generer_notification_mecanique(etat)

    data           = etat["donnees_camion"]
    alertes        = etat["alertes"]
    actions        = etat["actions_recommandees"]
    manuel         = etat["extraits_manuel"]
    vitesse_max    = etat["vitesse_recommandee_kmh"]
    action_vitesse = etat["action_vitesse_texte"]
    titre_genere   = etat["titre_genere"] or Genere_titre(
        alertes, data.get("load_tonnes"), data.get("charge_max_autorisee_tonnes", 30.0)  # FIX 1
    )

    action_grave_propre = calculer_action_technique(alertes, actions)
    nb_rouge = sum(1 for a in alertes if "[ROUGE]" in a)
    nb_jaune = sum(1 for a in alertes if "[JAUNE]" in a)

    capteurs_cles = {
        k: data[k] for k in
        ["current_speed_kmh", "distance_covered_km", "total_distance_km",
         "progress_percent", "load_tonnes", "position"]
        if k in data and data[k] is not None
    }
    # FIX 3 : position deja string dans le simulateur corrige
    # Si c'est encore un dict (compatibilite ancienne version), on le convertit
    if isinstance(capteurs_cles.get("position"), dict):
        pos = capteurs_cles["position"]
        capteurs_cles["position"] = f"lat={pos.get('lat')}, lon={pos.get('lon')}"

    capteurs_txt = "\n".join(f"{k}: {v}" for k, v in capteurs_cles.items())

    alertes_propres = [
        re.sub(r"\s*\([^)]*\)", "", re.sub(r"\s*\[[→↑↓][^\]]*\]", "", a)).strip()
        for a in alertes
    ]
    alertes_txt = "\n".join(f"- {a}" for a in alertes_propres)

    prompt = f"""### [titre_genere]
{titre_genere}

### [ALERTES_ACTIVES] ({len(alertes)} alerte(s) : ROUGE={nb_rouge} JAUNE={nb_jaune})
{alertes_txt}

### [ACTION_VITESSE]
{action_vitesse}

### [ACTION_TECHNIQUE]
{action_grave_propre}

### [VITESSE_MAX_KMH]
{vitesse_max} km/h

### Capteurs
{capteurs_txt}

### Manuel Volvo (extrait)
{manuel or "Aucun extrait."}"""

    total_estime = compter_tokens_approx(SYSTEM_NOTIF_ + prompt) + 300
    if total_estime > TOKEN_LIMIT_INPUT:
        budget = TOKEN_LIMIT_INPUT - compter_tokens_approx(SYSTEM_NOTIF_) - 300
        prompt = tronquer_texte(prompt, budget)
        logger.warning(" Prompt tronque")

    notification   = None
    modele_utilise = LLM_MODEL

    for retry_num in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f" LLM tentative {retry_num}/{MAX_RETRIES} | {modele_utilise}")
            completion = groq_client_notif.chat.completions.create(
                model=modele_utilise,
                messages=[
                    {"role": "system", "content": SYSTEM_NOTIF_},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
                top_p=1.0,
                stream=False,
            )
            notification = completion.choices[0].message.content.strip()
            _last_llm_call_time = time.time()  # Update timestamp after successful LLM call
            break
        except Exception as e:
            logger.warning(f" Tentative {retry_num} : {str(e)[:80]}")
            if "413" in str(e) or "too large" in str(e).lower():
                if modele_utilise != FALLBACK_MODEL:
                    modele_utilise = FALLBACK_MODEL
                    continue
                return generer_notification_mecanique(etat)
            if retry_num < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
            else:
                return generer_notification_mecanique(etat)

    if not notification:
        return generer_notification_mecanique(etat)

    # -- Post-traitement ---------------------------------------------
    notification = re.sub(r"<think>.*?</think>", "", notification, flags=re.DOTALL).strip()
    notification = re.sub(
        r"(\*\*Titre\*\*\s*:\s*)(.+?)(\n)",
        lambda m: m.group(1) + nettoyer_titre(titre_genere) + m.group(3),
        notification, count=1
    )
    notification, injection_ok = injecter_action2_robuste(notification, action_grave_propre, logger)
    if not injection_ok:
        notification = re.sub(r"(1\..+?\n)", f"\\g<1>2. {action_grave_propre}\n", notification, count=1)

    notification = re.sub(r"\s*\[[→↑↓][^\]]*\]", "", notification)
    notification = re.sub(r"\s*\([^)]*\)", "", notification)

    statut = "CONTINUER"
    m      = re.search(
        r"\*\*Statut final\*\*\s*:\s*(ARRET IMMEDIAT|ARRÊT IMMÉDIAT|REDUIRE VITESSE|RÉDUIRE VITESSE|CONTINUER)",
        notification, re.IGNORECASE,
    )
    if m:
        val = m.group(1).upper()
        if "ARRET" in val or "ARRÊT" in val:       statut = "ARRET IMMEDIAT"
        elif "REDUIRE" in val or "RÉDUIRE" in val: statut = "REDUIRE VITESSE"

    if titre_genere.startswith("CRITIQUE") and statut != "ARRET IMMEDIAT":
        statut = "ARRET IMMEDIAT"
    elif titre_genere.startswith("ATTENTION") and statut == "CONTINUER" and nb_jaune > 0:
        statut = "REDUIRE VITESSE"

    validation_result = valider_notification(notification, titre_genere, action_grave_propre, logger)
    logger.info(
        f" LLMNode -> {len(notification)} chars | {statut} | "
        f"Validation : {'[OK]' if validation_result['globally_valid'] else '[WARNING]'}"
    )
    return {**etat, "notification": notification, "statut_final": statut, "validation_status": validation_result}

# ==================================================================
# 14 - FALLBACK MECANIQUE
# ==================================================================
def generer_notification_mecanique(etat: EtatNotification) -> EtatNotification:
    data    = etat["donnees_camion"]
    alertes = etat["alertes"]
    nb_r    = sum(1 for a in alertes if "[ROUGE]" in a)
    nb_j    = sum(1 for a in alertes if "[JAUNE]" in a)
    titre   = nettoyer_titre(etat["titre_genere"])

    dist  = data.get("distance_covered_km", "N/A")
    total = data.get("total_distance_km", 60)
    prog  = data.get("progress_percent", "N/A")

    action_vitesse = etat["action_vitesse_texte"]
    action_tech    = calculer_action_technique(alertes, etat["actions_recommandees"])
    statut         = "ARRET IMMEDIAT" if nb_r > 0 else ("REDUIRE VITESSE" if nb_j > 0 else "CONTINUER")

    alertes_propres = [
        re.sub(r"\s*\([^)]*\)", "", re.sub(r"\s*\[[→↑↓][^\]]*\]", "", a)).strip()
        for a in alertes
    ]
    points = "\n".join(f"- {a}" for a in alertes_propres)

    notification = (
        f"**Titre** : {titre}\n"
        f"**Etat actuel** : {dist} km / {total} km — {prog}% — "
        f"{len(alertes)} alerte(s) active(s) : ROUGE={nb_r} JAUNE={nb_j}\n"
        f"**Points critiques** :\n{points}\n"
        f"**Actions immediates** :\n"
        f"1. {action_vitesse}\n"
        f"2. {action_tech}\n"
        f"3. Informer le superviseur de flotte.\n"
        f"**Statut final** : {statut}"
    )
    logger.warning(f" Fallback mecanique | Statut : {statut}")
    return {**etat, "notification": notification, "statut_final": statut, "validation_status": {}}

# ==================================================================
# 15 - NOEUD D : SAUVEGARDE (VERSION CORRIGEE - EVITE LES DOUBLONS)
# ==================================================================
def noeud_sauvegarde(etat: EtatNotification) -> EtatNotification:
    global _last_saved_notification

    if not etat["necessite_notification"] and not _has_alertes_reelles(etat["alertes"]):
        return etat

    # Chemin identique a history_service.NOTIFICATIONS_RAM_PATH
    notifications_ram_path = os.environ.get(
        "NOTIFICATIONS_RAM_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "notifications_ram.json")
    )

    # Construire une cle simplifiee pour comparer le contenu des alertes
    alertes_cle = "|".join(sorted(etat["alertes"]))  # Tri pour normaliser l'ordre

    now_time = time.time()
    last_time = _last_saved_notification.get("timestamp", 0)
    # Verifier si c'est un doublon recent (moins de 10 secondes)
    if (now_time - last_time) < 10.0 and \
       _last_saved_notification.get("titre") == etat["titre_genere"] and \
       _last_saved_notification.get("severite") == etat["severite"] and \
       _last_saved_notification.get("alertes_cle") == alertes_cle:
        logger.info("Notification ignoree (doublon recent) - sauvegarde evitee")
        return etat

    # Lire l'existant
    notifications = []
    if os.path.exists(notifications_ram_path):
        try:
            with open(notifications_ram_path, "r", encoding="utf-8") as f:
                notifications = json.load(f)
        except:
            pass

    # Construire l'entree (sans les capteurs, juste la notification)
    entry = {
        "cycle":             len(notifications) + 1,
        "timestamp":         etat["donnees_camion"].get("timestamp"),
        "severite":          etat["severite"],
        "statut_final":      etat["statut_final"],
        "vitesse_max_kmh":   etat["vitesse_recommandee_kmh"],
        "action_vitesse":    etat["action_vitesse_texte"],
        "titre":             nettoyer_titre(etat["titre_genere"]),
        "alertes":           etat["alertes"],
        "actions":           etat["actions_recommandees"],
        "notification":      etat["notification"],
        "validation_status": etat.get("validation_status", {}),
    }

    notifications.append(entry)

    # Ecrire
    try:
        os.makedirs(os.path.dirname(notifications_ram_path), exist_ok=True)
        with open(notifications_ram_path, "w", encoding="utf-8") as f:
            json.dump(notifications, f, ensure_ascii=False, indent=2)
        logger.info(f"Notification sauvegardee dans RAM -> #{entry['cycle']}")

        # Mettre a jour la memoire du dernier doublon
        _last_saved_notification = {
            "timestamp": now_time,
            "titre": etat["titre_genere"],
            "severite": etat["severite"],
            "alertes_cle": alertes_cle
        }
    except Exception as e:
        logger.error(f"Erreur sauvegarde RAM: {e}")

    return etat

# ==================================================================
# 16 - GRAPHE LANGGRAPH
# ==================================================================
def construire_graphe_notification() -> StateGraph:
    g = StateGraph(EtatNotification)
    g.add_node("regles",     noeud_regles)
    g.add_node("vector",     noeud_vector_notif)
    g.add_node("llm",        noeud_llm_notif)
    g.add_node("sauvegarde", noeud_sauvegarde)
    g.set_entry_point("regles")
    g.add_edge("regles",     "vector")
    g.add_edge("vector",     "llm")
    g.add_edge("llm",        "sauvegarde")
    g.add_edge("sauvegarde", END)
    return g.compile()

agent_notification = construire_graphe_notification()
logger.info("Agent Notification compile (version corrigee)")
logger.info(f"   Modele principal : {LLM_MODEL}")
logger.info(f"   Modele fallback  : {FALLBACK_MODEL}")
logger.info("   Correctifs actifs : is_finished guard / charge_max=30 / position string / reset_memory auto / dedoublonnage notif")

# ==================================================================
# 17 - FONCTION PRINCIPALE
# ==================================================================
def traiter_notification(donnees_camion: dict) -> dict:
    etat_initial: EtatNotification = {
        "donnees_camion":          donnees_camion,
        "alertes":                 [],
        "alertes_debug":           [],
        "severite":                "NORMAL",
        "actions_recommandees":    [],
        "necessite_notification":  False,
        "vitesse_recommandee_kmh": 80,
        "action_vitesse_texte":    "Maintenir vitesse actuelle.",
        "extraits_manuel":         "",
        "notification":            "",
        "statut_final":            "CONTINUER",
        "titre_genere":            "",
        "validation_status":       {},
    }
    return agent_notification.invoke(etat_initial)

# ==================================================================
# 18 - BOUCLE DE MONITORING
# ==================================================================
logger.info("\n" + "=" * 70)