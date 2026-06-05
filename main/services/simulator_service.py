"""
main_simulator_fixed.py — TruckMind Simulator (Version Corrigée)
=================================================================
Corrections appliquées vs version originale :
  ✅ FIX 1 : CHARGE_MAX_TONNES stocké en instance var (plus de dépendance global)
  ✅ FIX 2 : TOTAL_DISTANCE_KM stocké en instance var dans TruckState
  ✅ FIX 3 : to_dict() utilise self.total_distance_km (pas le global)
  ✅ FIX 4 : SimulatorService.step() ne modifie plus les globals dangereux
  ✅ FIX 5 : is_finished exposé clairement + guard dans to_dict()
  ✅ FIX 6 : position sérialisée en string "lat=X, lon=Y" pour le LLM
  ✅ FIX 7 : update_load() ne change plus la charge pendant une anomalie active
  ✅ FIX 8 : SEUIL_FREINS cohérent avec la Cellule 11 (JAUNE=60, ROUGE=80)
"""

import asyncio
import json
import random
import os
import math
from datetime import datetime, timedelta

# ===== Constantes du trajet (Valeurs par défaut) =====
# ✅ FIX : Ces constantes ne sont plus modifiées par SimulatorService
# Chaque instance TruckState stocke ses propres valeurs
DEFAULT_TOTAL_DISTANCE_KM = 60.0
START_LAT, START_LON = 35.7595, -5.8340
DEFAULT_END_LAT   = 35.5729
DEFAULT_END_LON   = -5.3628

JOURNEY_DURATION_HOURS = 1.0
UPDATE_INTERVAL_SEC    = 30
WRITE_INTERVAL_SEC     = 120

# ══════════════════════════════════════════════════════════════════
# SEUILS — Source de vérité (doit correspondre à SQLite thresholds)
# ✅ FIX 8 : SEUIL_FREINS_JAUNE = 60 (cohérent avec Cellule 11)
# ══════════════════════════════════════════════════════════════════
SEUIL_TEMP_JAUNE    = 100.0
SEUIL_TEMP_ROUGE    = 105.0

SEUIL_PNEU_JAUNE    =  90.0
SEUIL_PNEU_ROUGE    =  75.0
SEUIL_PNEU_HAUT     = 125.0

SEUIL_CONSO_JAUNE   =  35.0
SEUIL_CONSO_ROUGE   =  45.0

SEUIL_BATT_JAUNE    =  30.0
SEUIL_BATT_ROUGE    =  15.0

SEUIL_VIB_JAUNE     =   8.0
SEUIL_VIB_ROUGE     =  12.0

# ✅ FIX 8 : Aligné avec Cellule 11 (SEUIL_FREINS_JAUNE = 60, pas 70)
SEUIL_FREINS_JAUNE  =  60.0
SEUIL_FREINS_ROUGE  =  80.0

# ✅ FIX 1 : CHARGE_MAX_TONNES = 30 (cohérent avec Cellule 11 default=30)
CHARGE_MAX_TONNES   =  30.0
SEUIL_CHARGE_JAUNE  =  30.0
SEUIL_CHARGE_ROUGE  =  38.0

# ══════════════════════════════════════════════════════════════════
# DURÉES DES ANOMALIES (en nombre de steps de 30s)
# ══════════════════════════════════════════════════════════════════
ANOMALIE_DUREE_MIN = 4   # minimum 4 steps = 120s (1 cycle complet de lecture)
ANOMALIE_DUREE_MAX = 8   # maximum 8 steps = 240s (2 cycles de lecture)


# ══════════════════════════════════════════════════════════════════
# CATALOGUE DES SCÉNARIOS D'ANOMALIES DÉTAILLÉS
# ══════════════════════════════════════════════════════════════════
ANOMALIE_SCENARIOS = {

    # ────── TEMPÉRATURE MOTEUR ──────────────────────────────────
    "temp_surchauffe_legere": {
        "type": "temp",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(101, 104), 1),
        "description_fn": lambda v: f"⚠️ Température moteur élevée ({v}°C) — surchauffe légère",
        "probabilite": 0.015,
    },
    "temp_surchauffe_critique": {
        "type": "temp",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(106, 115), 1),
        "description_fn": lambda v: f"🔴 Température moteur critique ({v}°C) — arrêt recommandé",
        "probabilite": 0.012,
    },
    "temp_thermostat_defaillant": {
        "type": "temp",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(118, 130), 1),
        "description_fn": lambda v: f"🔴 Thermostat défaillant — température moteur ({v}°C) incontrôlée",
        "probabilite": 0.005,
    },
    "temp_radiateur_bouche": {
        "type": "temp",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(103, 108), 1),
        "description_fn": lambda v: f"⚠️ Possible radiateur bouché — temp ({v}°C) — vérifier circuit refroidissement",
        "probabilite": 0.008,
    },

    # ────── PRESSION PNEUS ──────────────────────────────────────
    "pneu_pression_basse_moderee": {
        "type": "pneu",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(80, 89), 1),
        "description_fn": lambda v: f"⚠️ Pression pneus insuffisante ({v} PSI) — perte lente détectée",
        "probabilite": 0.012,
    },
    "pneu_pression_critique": {
        "type": "pneu",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(60, 74), 1),
        "description_fn": lambda v: f"🔴 Pression pneus critique ({v} PSI) — risque d'éclatement",
        "probabilite": 0.007,
    },
    "pneu_surpression": {
        "type": "pneu",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(126, 138), 1),
        "description_fn": lambda v: f"⚠️ Surpression pneus ({v} PSI) — risque d'éclatement par chaleur",
        "probabilite": 0.006,
    },
    "pneu_crevason_progressive": {
        "type": "pneu",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(45, 65), 1),
        "description_fn": lambda v: f"🔴 Crevaison progressive détectée ({v} PSI) — arrêt immédiat",
        "probabilite": 0.005,
    },

    # ────── FREINS ──────────────────────────────────────────────
    "freins_usure_moderee": {
        "type": "freins",
        "niveau": "jaune",
        # ✅ FIX 8 : Valeurs alignées avec SEUIL_FREINS_JAUNE=60
        "valeur_fn": lambda: round(random.uniform(61, 79), 1),
        "description_fn": lambda v: f"⚠️ Usure freins modérée ({v}%) — maintenance à planifier",
        "probabilite": 0.012,
    },
    "freins_usure_critique": {
        "type": "freins",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(81, 90), 1),
        "description_fn": lambda v: f"🔴 Freins très usés ({v}%) — remplacement urgent des plaquettes",
        "probabilite": 0.008,
    },
    "freins_defaillance_totale": {
        "type": "freins",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(91, 99), 1),
        "description_fn": lambda v: f"🔴 DÉFAILLANCE FREINS ({v}%) — ARRÊT D'URGENCE requis",
        "probabilite": 0.004,
    },
    "freins_surchauffe": {
        "type": "freins",
        "niveau": "jaune",
        # ✅ FIX 8 : Début à 61% (au-dessus du seuil JAUNE=60)
        "valeur_fn": lambda: round(random.uniform(61, 79), 1),
        "description_fn": lambda v: f"⚠️ Freins en surchauffe ({v}%) — descente prolongée détectée",
        "probabilite": 0.007,
    },

    # ────── BATTERIE ────────────────────────────────────────────
    "batterie_faible_moderee": {
        "type": "batterie",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(20, 29), 1),
        "description_fn": lambda v: f"⚠️ Batterie faible ({v}%) — recharge recommandée prochainement",
        "probabilite": 0.010,
    },
    "batterie_critique": {
        "type": "batterie",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(8, 14), 1),
        "description_fn": lambda v: f"🔴 Batterie critique ({v}%) — risque de panne démarrage imminente",
        "probabilite": 0.007,
    },
    "batterie_decharge_rapide": {
        "type": "batterie",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(5, 12), 1),
        "description_fn": lambda v: f"🔴 Décharge rapide batterie ({v}%) — alternateur ou court-circuit suspect",
        "probabilite": 0.005,
    },
    "batterie_vieillissement": {
        "type": "batterie",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(22, 28), 1),
        "description_fn": lambda v: f"⚠️ Batterie vieillissante ({v}%) — capacité réduite — planifier remplacement",
        "probabilite": 0.008,
    },

    # ────── VIBRATIONS ──────────────────────────────────────────
    "vibrations_moderees": {
        "type": "vibrations",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(8.0, 11.5), 2),
        "description_fn": lambda v: f"⚠️ Vibrations anormales ({v} mm/s) — vérifier équilibrage roues",
        "probabilite": 0.010,
    },
    "vibrations_critiques": {
        "type": "vibrations",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(12.0, 17.0), 2),
        "description_fn": lambda v: f"🔴 Vibrations critiques ({v} mm/s) — roulement ou suspension défaillant",
        "probabilite": 0.007,
    },
    "vibrations_moteur_desaccorde": {
        "type": "vibrations",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(14.0, 20.0), 2),
        "description_fn": lambda v: f"🔴 Vibrations excessives moteur ({v} mm/s) — désaccordement cylindres suspect",
        "probabilite": 0.004,
    },
    "vibrations_chaussee_degradee": {
        "type": "vibrations",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(9.0, 13.0), 2),
        "description_fn": lambda v: f"⚠️ Vibrations élevées ({v} mm/s) — possible chaussée dégradée ou amortisseurs",
        "probabilite": 0.008,
    },

    # ────── CONSOMMATION CARBURANT ──────────────────────────────
    "conso_elevee_moderee": {
        "type": "conso",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(36, 44), 1),
        "description_fn": lambda v: f"⚠️ Consommation élevée ({v} L/100km) — vérifier filtre air / charge",
        "probabilite": 0.008,
    },
    "conso_excessive": {
        "type": "conso",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(45, 55), 1),
        "description_fn": lambda v: f"🔴 Consommation excessive ({v} L/100km) — injection ou turbo défaillant",
        "probabilite": 0.005,
    },
    "conso_fuite_carburant": {
        "type": "conso",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(50, 65), 1),
        "description_fn": lambda v: f"🔴 Consommation anormale ({v} L/100km) — fuite carburant possible",
        "probabilite": 0.003,
    },
    "conso_filtre_bouche": {
        "type": "conso",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(37, 43), 1),
        "description_fn": lambda v: f"⚠️ Consommation ({v} L/100km) — filtre à carburant potentiellement bouché",
        "probabilite": 0.006,
    },

    # ────── QUALITÉ HUILE ───────────────────────────────────────────
    "huile_faible_moderee": {
        "type": "huile",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(55, 69), 1),
        "description_fn": lambda v: f"⚠️ Qualité huile faible ({v}%) — changement recommandé prochainement",
        "probabilite": 0.010,
    },
    "huile_critique": {
        "type": "huile",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(15, 45), 1),
        "description_fn": lambda v: f"🔴 Qualité huile critique ({v}%) — risque d'usure moteur, changement immédiat requis",
        "probabilite": 0.007,
    },
    "huile_contamination": {
        "type": "huile",
        "niveau": "rouge",
        "valeur_fn": lambda: round(random.uniform(10, 35), 1),
        "description_fn": lambda v: f"🔴 Contamination huile détectée ({v}%) — présence possible de carburant ou eau",
        "probabilite": 0.005,
    },
    "huile_vieillissement": {
        "type": "huile",
        "niveau": "jaune",
        "valeur_fn": lambda: round(random.uniform(60, 74), 1),
        "description_fn": lambda v: f"⚠️ Huile vieillissante ({v}%) — planifier changement sous 500 km",
        "probabilite": 0.008,
    },
}


# ══════════════════════════════════════════════════════════════════
# VILLES MAROCAINES
# ══════════════════════════════════════════════════════════════════
MOROCCAN_CITIES = {
    "Tétouan":    (35.5729, -5.3628),
    "Casablanca": (33.5731, -7.5898),
    "Rabat":      (34.0209, -6.8416),
    "Fès":        (34.0331, -5.0003),
    "Marrakech":  (31.6295, -7.9811),
    "Tanger":     (35.7595, -5.8340),
    "Agadir":     (30.4278, -9.5981),
    "Meknès":     (33.8935, -5.5473),
    "Oujda":      (34.6814, -1.9153),
    "Kenitra":    (34.2610, -6.5802),
}

# ══════════════════════════════════════════════════════════════════
# TEMPS DE VOYAGE RÉALISTES (depuis Tanger)
# ══════════════════════════════════════════════════════════════════
TRAVEL_TIMES_HOURS = {
    "Tétouan": 1.0,
    "Fès": 4.0,
    "Casablanca": 5.0,
    "Rabat": 3.0,
    "Marrakech": 6.0,
    "Agadir": 8.0,
    "Meknès": 4.0,
    "Oujda": 11.0,
    "Kenitra": 3.0,
}


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ══════════════════════════════════════════════════════════════════
# CLASSE PRINCIPALE TruckState
# ══════════════════════════════════════════════════════════════════
class TruckState:
    """
    ✅ FIX 1 + 2 : Toutes les constantes de trajet sont des attributs
    d'instance — plus aucune dépendance aux variables globales mutables.
    """

    def __init__(self, end_lat=DEFAULT_END_LAT, end_lon=DEFAULT_END_LON,
                 total_distance_km=DEFAULT_TOTAL_DISTANCE_KM,
                 charge_max_tonnes=CHARGE_MAX_TONNES):
        # ✅ FIX 2 : Stocker les paramètres de trajet en instance
        self._end_lat          = end_lat
        self._end_lon          = end_lon
        self._total_distance   = total_distance_km
        self._charge_max       = charge_max_tonnes
        self.reset_journey()

    def reset_journey(self):
        self.truck_id              = "Volvo_FH_001"
        self.journey_start_time   = datetime.now()
        self.timestamp            = datetime.now()
        self.distance_covered_km  = 0.0
        self.current_speed_kmh    = 0.0
        self.engine_status        = "Moteur arrêté"
        self.is_engine_on         = False

        self.load_tonnes          = 27.0
        self.surcharge_niveau     = "none"

        # Capteurs — valeurs initiales normales
        self.temperature_moteur_c  = 20.0
        self.pression_pneus_psi    = 112.0
        self.consommation_l_100km  = 25.0
        self.batterie_percent      = 100.0
        self.vibrations_level      = 0.0
        self.freins_usure_percent  = 10.0
        self.fuel_level_liters     = 400.0
        self.qualite_huile         = 85.0

        # Drapeaux d'alerte
        self.temperature_moteur_alerte = False
        self.pression_pneus_alerte     = False
        self.consommation_elevee       = False
        self.batterie_faible           = False
        self.vibrations_anormales      = False
        self.freins_defectueux         = False

        self.anomalie_detectee     = False
        self.description_anomalie  = "Début du trajet"
        self.is_finished           = False
        self.elapsed_sec           = 0
        self.next_maintenance_due  = "2025-04-15"
        self.avg_speed_kmh         = 0.0
        self.journey_status        = "Prêt à démarrer"

        # Gestionnaire d'anomalie active
        self._anomalie_type        = None
        self._anomalie_scenario    = None
        self._anomalie_steps_left  = 0
        self._anomalie_valeur      = None

    def start_engine(self):
        if not self.is_engine_on:
            self.is_engine_on         = True
            self.engine_status        = "Moteur en marche"
            self.description_anomalie = "Moteur démarré - prêt à partir"

    def get_position(self):
        """✅ FIX 6 : Retourne un dict avec lat/lon (pour compatibilité interne)."""
        if self.distance_covered_km >= self._total_distance:
            return {"lat": round(self._end_lat, 5), "lon": round(self._end_lon, 5)}
        p = self.distance_covered_km / self._total_distance
        return {
            "lat": round(START_LAT + (self._end_lat - START_LAT) * p, 5),
            "lon": round(START_LON + (self._end_lon - START_LON) * p, 5),
        }

    def get_position_str(self) -> str:
        """✅ FIX 6 : Version string pour le LLM — pas de dict brut."""
        pos = self.get_position()
        return f"lat={pos['lat']}, lon={pos['lon']}"

    # ── Charge dynamique ─────────────────────────────────────────
    def update_load(self):
        # ✅ FIX 7 : Ne pas changer la charge pendant une anomalie active
        # (évite d'invalider les calculs de surcharge en cours)
        if self._anomalie_steps_left > 0:
            return

        rand = random.random()
        if rand < 0.70:
            self.load_tonnes      = round(random.uniform(25.0, 29.5), 1)
            self.surcharge_niveau = "none"
        elif rand < 0.90:
            self.load_tonnes      = round(random.uniform(31.0, 37.0), 1)
            self.surcharge_niveau = "jaune"
        elif rand < 0.98:
            self.load_tonnes      = round(random.uniform(38.0, 42.0), 1)
            self.surcharge_niveau = "rouge"
        else:
            self.load_tonnes      = round(random.uniform(43.0, 48.0), 1)
            self.surcharge_niveau = "rouge"

    # ── Gestionnaire d'anomalies ─────────────────────────────────
    def trigger_dynamic_anomalies(self) -> bool:
        """Retourne True si une nouvelle anomalie a été déclenchée."""

        # A. Gestion de l'anomalie en cours
        if self._anomalie_steps_left > 0:
            self._anomalie_steps_left -= 1
            if self._anomalie_steps_left == 0:
                self._reset_anomalie_capteur()
                self._anomalie_type     = None
                self._anomalie_scenario = None
                self._anomalie_valeur   = None
                print("  🟢 Anomalie terminée → retour à la normale")
            return False

        # B. Tirage probabiliste dans le catalogue
        rand = random.random()
        seuil_cumule    = 0.0
        scenario_choisi = None

        for cle, sc in ANOMALIE_SCENARIOS.items():
            seuil_cumule += sc["probabilite"]
            if rand < seuil_cumule:
                scenario_choisi = (cle, sc)
                break

        if scenario_choisi is None:
            if self.anomalie_detectee:
                self._reset_anomalie_capteur()
                self._anomalie_type     = None
                self._anomalie_scenario = None
            return False

        cle_sc, sc  = scenario_choisi
        valeur       = sc["valeur_fn"]()
        description  = sc["description_fn"](valeur)
        duree        = random.randint(ANOMALIE_DUREE_MIN, ANOMALIE_DUREE_MAX)

        self._appliquer_scenario(sc["type"], sc["niveau"], valeur)
        self.anomalie_detectee        = True
        self.description_anomalie     = description
        self._anomalie_type           = sc["type"]
        self._anomalie_scenario       = cle_sc
        self._anomalie_valeur         = valeur
        self._anomalie_steps_left     = duree

        print(f"  🔴 NOUVELLE anomalie [{cle_sc}] : {sc['type']} = {valeur} "
              f"| niveau : {sc['niveau']} | durée : {duree} steps = {duree * 30}s")
        return True

    def _appliquer_scenario(self, type_anomalie: str, niveau: str, valeur: float):
        if type_anomalie == "temp":
            self.temperature_moteur_c      = valeur
            self.temperature_moteur_alerte = True
        elif type_anomalie == "pneu":
            self.pression_pneus_psi    = valeur
            self.pression_pneus_alerte = True
        elif type_anomalie == "freins":
            self.freins_usure_percent = valeur
            self.freins_defectueux    = (valeur >= SEUIL_FREINS_ROUGE)
        elif type_anomalie == "batterie":
            self.batterie_percent = valeur
            self.batterie_faible  = True
        elif type_anomalie == "vibrations":
            self.vibrations_level     = valeur
            self.vibrations_anormales = True
        elif type_anomalie == "conso":
            self.consommation_l_100km = valeur
            self.consommation_elevee  = True
        elif type_anomalie == "huile":
            self.qualite_huile = valeur

    def _reset_anomalie_capteur(self):
        """Remet le capteur de l'anomalie active à une valeur normale."""
        t        = self._anomalie_type
        progress = self.distance_covered_km / self._total_distance if self._total_distance > 0 else 0

        if t == "temp":
            self.temperature_moteur_c      = round(80.0 + progress * 10.0 + random.uniform(-2, 2), 1)
            self.temperature_moteur_alerte = False
        elif t == "pneu":
            self.pression_pneus_psi    = round(random.uniform(100.0, 115.0), 1)
            self.pression_pneus_alerte = False
        elif t == "freins":
            self.freins_usure_percent = round(10.0 + progress * 20.0 + random.uniform(-1, 1), 1)
            self.freins_defectueux    = False
        elif t == "batterie":
            self.batterie_percent = max(70.0, self.batterie_percent)
            self.batterie_faible  = False
        elif t == "vibrations":
            self.vibrations_level     = round(random.uniform(1.5, 5.0), 2)
            self.vibrations_anormales = False
        elif t == "conso":
            load_factor               = 1.0 + (self.load_tonnes / 50.0) * 0.25
            self.consommation_l_100km = round(22.0 * load_factor + random.uniform(-1, 1), 1)
            self.consommation_elevee  = False
        elif t == "huile":
            base_huile = 85.0 - progress * 15.0 - max(0, self.load_tonnes - 30.0) * 0.3
            self.qualite_huile = round(max(70.0, base_huile + random.uniform(-1, 1)), 1)

        self.anomalie_detectee    = False
        self.description_anomalie = "État normal - retour à la normale après alerte"

    # ── Vitesse réaliste ─────────────────────────────────────────
    def get_realistic_speed(self):
        if not self.is_engine_on or self.is_finished:
            return 0.0
        base = 60.0
        if self.temperature_moteur_alerte:      base *= 0.70
        if self.freins_defectueux:              base *= 0.80
        if self.vibrations_anormales:           base *= 0.85
        if self.surcharge_niveau == "rouge":    base *= 0.80
        elif self.surcharge_niveau == "jaune":  base *= 0.90
        return max(0.0, base + random.uniform(-3, 3))

    # ── Mise à jour des capteurs ─────────────────────────────────
    def update_sensors(self):
        if not self.is_engine_on:
            self.temperature_moteur_c = 25.0
            self.current_speed_kmh    = 0.0
            return

        progress = self.distance_covered_km / self._total_distance if self._total_distance > 0 else 0
        load     = self.load_tonnes

        if self._anomalie_type != "temp":
            base_temp = 80.0 + progress * 15.0 + max(0, load - 30.0) * 1.0
            self.temperature_moteur_c      = round(base_temp + random.uniform(-2, 2), 1)
            self.temperature_moteur_alerte = (self.temperature_moteur_c >= SEUIL_TEMP_JAUNE)

        if self._anomalie_type != "pneu":
            base_pneu = 112.0 - max(0, load - 30.0) * 0.4 - progress * 4.0
            self.pression_pneus_psi    = round(base_pneu + random.uniform(-1.5, 1.5), 1)
            self.pression_pneus_alerte = (
                self.pression_pneus_psi < SEUIL_PNEU_JAUNE
                or self.pression_pneus_psi > SEUIL_PNEU_HAUT
            )

        if self._anomalie_type != "conso":
            load_factor  = 1.0 + (load / 50.0) * 0.25
            speed_factor = 1.0 + (self.current_speed_kmh / 100.0) * 0.15
            self.consommation_l_100km = round(22.0 * load_factor * speed_factor + random.uniform(-1, 1), 1)
            self.consommation_elevee  = (self.consommation_l_100km > SEUIL_CONSO_JAUNE)

        rate = (self.consommation_l_100km / 100.0) * (self.current_speed_kmh / 3600.0)
        self.fuel_level_liters = max(0.0, round(self.fuel_level_liters - rate, 2))

        if self._anomalie_type != "batterie":
            self.batterie_percent = max(0.0, round(self.batterie_percent - 0.001, 1))
            self.batterie_faible  = (self.batterie_percent < SEUIL_BATT_JAUNE)

        if self._anomalie_type != "vibrations":
            spd_vib = (self.current_speed_kmh / 100.0) * 2.5
            if self.freins_defectueux:     spd_vib *= 1.4
            if self.pression_pneus_alerte: spd_vib *= 1.25
            load_vib              = max(0, load - 30.0) * 0.12
            self.vibrations_level = round(2.0 + spd_vib + load_vib + random.uniform(-0.5, 0.5), 2)
            self.vibrations_anormales = (self.vibrations_level > SEUIL_VIB_JAUNE)

        if self._anomalie_type != "freins":
            self.freins_usure_percent = round(
                10.0 + progress * 20.0 + max(0, load - 30.0) * 0.4 + random.uniform(-0.5, 0.5), 1
            )
            self.freins_defectueux = (self.freins_usure_percent >= SEUIL_FREINS_ROUGE)

        if self._anomalie_type != "huile":
            # Qualité huile diminue progressivement avec le temps et la charge
            base_huile = 85.0 - progress * 15.0 - max(0, load - 30.0) * 0.3
            self.qualite_huile = round(max(0.0, base_huile + random.uniform(-1, 1)), 1)

    def calculate_elapsed_time(self):
        if self.is_engine_on:
            self.elapsed_sec = int((datetime.now() - self.journey_start_time).total_seconds())
        return self.elapsed_sec

    def step(self, time_delta_sec=30) -> bool:
        """✅ Retourne True si une nouvelle anomalie a été créée."""
        if self.is_finished:
            return False

        if not self.is_engine_on and self.distance_covered_km == 0:
            self.start_engine()

        self.calculate_elapsed_time()
        self.timestamp         = datetime.now()
        self.current_speed_kmh = self.get_realistic_speed()
        self.distance_covered_km += (self.current_speed_kmh / 3600.0) * time_delta_sec

        if self.elapsed_sec > 0:
            self.avg_speed_kmh = round((self.distance_covered_km / self.elapsed_sec) * 3600, 2)

        # ✅ FIX 5 : Vérification is_finished avec self._total_distance
        if self.distance_covered_km >= self._total_distance:
            self.distance_covered_km  = self._total_distance
            self.is_finished          = True
            self.is_engine_on         = False
            self.engine_status        = "Moteur arrêté"
            self.journey_status       = f"Arrivée à destination ✓"
            self.description_anomalie = "Trajet terminé avec succès !"
            self.current_speed_kmh    = 0.0
            return False

        # Ordre correct : charge → anomalies → capteurs
        self.update_load()
        nouvelle_anomalie = self.trigger_dynamic_anomalies()
        self.update_sensors()

        progress_pct        = (self.distance_covered_km / self._total_distance) * 100
        self.journey_status = f"En cours : {progress_pct:.1f}% du trajet"
        return nouvelle_anomalie

    def to_dict(self):
        """
        ✅ FIX 2 : Utilise self._total_distance (pas le global TOTAL_DISTANCE_KM)
        ✅ FIX 6 : position est une STRING "lat=X, lon=Y" → lisible par le LLM
        ✅ FIX 1 : charge_max_autorisee_tonnes = self._charge_max (cohérent avec Cellule 11)
        ✅ FIX 5 : is_finished exposé clairement
        """
        dist   = self._total_distance if self._total_distance > 0 else 1
        prog   = round((self.distance_covered_km / dist) * 100, 1)

        return {
            "truck_id":                    self.truck_id,
            "timestamp":                   self.timestamp.isoformat(),
            "journey_status":              self.journey_status,
            "engine_status":               self.engine_status,

            # ✅ FIX 6 : string au lieu de dict — lisible par LLM
            "position":                    self.get_position_str(),

            "distance_covered_km":         round(self.distance_covered_km, 2),
            "total_distance_km":           self._total_distance,   # ✅ FIX 2
            "progress_percent":            prog,
            "current_speed_kmh":           round(self.current_speed_kmh, 2),
            "avg_speed_kmh":               self.avg_speed_kmh,
            "elapsed_time_sec":            self.elapsed_sec,
            "elapsed_time_formatted":      self.format_time(self.elapsed_sec),
            "estimated_arrival_time":      self.calculate_eta(),

            # ✅ FIX 1 : Utilise self._charge_max — valeur = 30.0, cohérent avec Cellule 11
            "load_tonnes":                 self.load_tonnes,
            "charge_max_autorisee_tonnes": self._charge_max,
            "surcharge_active":            self.load_tonnes > self._charge_max,
            "surcharge_niveau":            self.surcharge_niveau,
            "charge_seuil_jaune":          SEUIL_CHARGE_JAUNE,
            "charge_seuil_rouge":          SEUIL_CHARGE_ROUGE,
            "fuel_level_liters":           round(self.fuel_level_liters, 2),

            # Clés renommées pour correspondre à la table thresholds
            "consommation_carburant":      round(self.consommation_l_100km, 2),
            "temperature_moteur":          round(self.temperature_moteur_c, 1),
            "pression_pneus":              round(self.pression_pneus_psi, 1),
            "etat_batterie":               round(self.batterie_percent, 1),
            "niveaux_vibration":           round(self.vibrations_level, 2),
            "freins_usure_percent":        round(self.freins_usure_percent, 1),
            # ✅ Ajout pour compatibilité avec notification_service.py
            "score_predictif":             0.0,  # Simulé - peut être calculé selon la logique métier
            "qualite_huile":               round(self.qualite_huile, 1),

            # Drapeaux d'alerte
            "temperature_moteur_alerte":   self.temperature_moteur_alerte,
            "pression_pneus_alerte":       self.pression_pneus_alerte,
            "consommation_elevee":         self.consommation_elevee,
            "batterie_faible":             self.batterie_faible,
            "vibrations_anormales":        self.vibrations_anormales,
            "freins_defectueux":           self.freins_defectueux,

            # Anomalie
            "anomalie_detectee":           self.anomalie_detectee,
            "anomalie_type_actif":         self._anomalie_type,
            "anomalie_scenario_actif":     self._anomalie_scenario,
            "anomalie_steps_restants":     self._anomalie_steps_left,
            "description_anomalie":        self.description_anomalie,

            # ✅ FIX 5 : is_finished clairement exposé
            "is_finished":                 self.is_finished,
            "next_maintenance_due":        self.next_maintenance_due,
        }

    @staticmethod
    def format_time(seconds):
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

    def calculate_eta(self):
        if self.current_speed_kmh <= 0 or self.is_finished:
            return "Arrivé à destination"
        remaining = self._total_distance - self.distance_covered_km
        eta       = datetime.now() + timedelta(hours=remaining / self.current_speed_kmh)
        return eta.strftime("%H:%M:%S")


# ══════════════════════════════════════════════════════════════════
# SimulatorService
# ✅ FIX 4 : Ne modifie PLUS les variables globales END_LAT/END_LON/TOTAL_DISTANCE_KM
# Crée une nouvelle instance TruckState avec les bons paramètres
# ══════════════════════════════════════════════════════════════════
class SimulatorService:
    def __init__(self):
        self.destination_city = "Tétouan"
        self.is_running       = False
        # ✅ FIX 4 : Créer TruckState avec les paramètres de destination
        end_lat, end_lon = MOROCCAN_CITIES["Tétouan"]
        # Utiliser le temps de voyage réaliste au lieu de la distance haversine
        travel_hours = TRAVEL_TIMES_HOURS.get("Tétouan", 1.0)
        # Estimer la distance routière (environ 80 km/h de vitesse moyenne sur les routes marocaines)
        total_dist = travel_hours * 80
        self.truck_state = TruckState(end_lat=end_lat, end_lon=end_lon,
                                      total_distance_km=total_dist)

    def set_destination(self, city: str):
        """✅ FIX 4 : Pas de mutation de globals — stocke les paramètres localement."""
        if city in MOROCCAN_CITIES:
            self.destination_city = city

    def start_journey(self):
        """✅ FIX 4 : Crée un nouveau TruckState avec les bons paramètres."""
        end_lat, end_lon = MOROCCAN_CITIES[self.destination_city]
        # Utiliser le temps de voyage réaliste au lieu de la distance haversine
        travel_hours = TRAVEL_TIMES_HOURS.get(self.destination_city, 1.0)
        # Estimer la distance routière (environ 80 km/h de vitesse moyenne sur les routes marocaines)
        total_dist = travel_hours * 80
        self.truck_state = TruckState(
            end_lat=end_lat,
            end_lon=end_lon,
            total_distance_km=total_dist,
            charge_max_tonnes=CHARGE_MAX_TONNES,  # ✅ FIX 1 : 30.0
        )
        self.truck_state.start_engine()
        self.is_running = True
        print(f"🚛 Départ Tanger → {self.destination_city} | Distance : {total_dist:.1f} km | Durée estimée : {travel_hours}h")

    def stop_journey(self):
        self.is_running = False

    def step(self):
        """✅ FIX 4 : Délègue directement à truck_state — plus de mutation globale."""
        if not self.is_running:
            return False
        nouvelle_anomalie = self.truck_state.step(time_delta_sec=30)
        if self.truck_state.is_finished:
            self.is_running = False
        return nouvelle_anomalie

    def get_data(self) -> dict:
        return self.truck_state.to_dict()


# ===== Instance globale =====
simulator = SimulatorService()