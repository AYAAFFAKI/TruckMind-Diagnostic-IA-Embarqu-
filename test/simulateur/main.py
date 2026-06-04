import asyncio
import json
import random
import os
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TruckMind - Simulation du camion Volvo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Constantes du trajet (Tanger -> Tétouan) =====
TOTAL_DISTANCE_KM = 60.0
START_LAT, START_LON = 35.7595, -5.8340
END_LAT,   END_LON   = 35.5729, -5.3628

JOURNEY_DURATION_HOURS = 1.0
UPDATE_INTERVAL_SEC    = 30
WRITE_INTERVAL_SEC     = 120

JSON_FILE_PATH = r"C:\Users\ayaaf\OneDrive\Belgeler\truck_rag_sys\test\data_reelle\camion_volvo.json"

# ══════════════════════════════════════════════════════════════════
# SEUILS — Source de vérité (doit correspondre à SQLite thresholds)
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

SEUIL_FREINS_JAUNE  =  70.0
SEUIL_FREINS_ROUGE  =  80.0

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
        "valeur_fn": lambda: round(random.uniform(71, 79), 1),
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
        "valeur_fn": lambda: round(random.uniform(73, 82), 1),
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
}


class TruckState:
    def __init__(self):
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

        # ══════════════════════════════════════════════════════════
        # GESTIONNAIRE D'ANOMALIE ACTIVE
        # ══════════════════════════════════════════════════════════
        self._anomalie_type        = None
        self._anomalie_scenario    = None   # clé du scénario actif
        self._anomalie_steps_left  = 0
        self._anomalie_valeur      = None

    def start_engine(self):
        if not self.is_engine_on:
            self.is_engine_on         = True
            self.engine_status        = "Moteur en marche"
            self.description_anomalie = "Moteur démarré - prêt à partir"

    def get_position(self):
        if self.distance_covered_km >= TOTAL_DISTANCE_KM:
            return {"lat": round(END_LAT, 5), "lon": round(END_LON, 5)}
        p = self.distance_covered_km / TOTAL_DISTANCE_KM
        return {
            "lat": round(START_LAT + (END_LAT - START_LAT) * p, 5),
            "lon": round(START_LON + (END_LON - START_LON) * p, 5),
        }

    # ══════════════════════════════════════════════════════════════
    # CHARGE DYNAMIQUE
    # ══════════════════════════════════════════════════════════════
    def update_load(self):
        rand = random.random()
        if rand < 0.70:
            self.load_tonnes = round(random.uniform(25.0, 29.5), 1)
            self.surcharge_niveau = "none"
        elif rand < 0.90:
            self.load_tonnes = round(random.uniform(31.0, 37.0), 1)
            self.surcharge_niveau = "jaune"
        elif rand < 0.98:
            self.load_tonnes = round(random.uniform(38.0, 42.0), 1)
            self.surcharge_niveau = "rouge"
        else:
            self.load_tonnes = round(random.uniform(43.0, 48.0), 1)
            self.surcharge_niveau = "rouge"

    # ══════════════════════════════════════════════════════════════
    # GESTIONNAIRE D'ANOMALIES AVEC CATALOGUE DIVERSIFIÉ
    # ══════════════════════════════════════════════════════════════
    def trigger_dynamic_anomalies(self) -> bool:
        """
        Sélectionne aléatoirement parmi le catalogue ANOMALIE_SCENARIOS.
        Retourne True si une nouvelle anomalie a été déclenchée.
        """

        # ── A. Gestion de l'anomalie en cours ─────────────────────
        if self._anomalie_steps_left > 0:
            self._anomalie_steps_left -= 1

            if self._anomalie_steps_left == 0:
                self._reset_anomalie_capteur()
                self._anomalie_type     = None
                self._anomalie_scenario = None
                self._anomalie_valeur   = None
                print(f"  🟢 Anomalie terminée → retour à la normale")
            return False

        # ── B. Tirage probabiliste dans le catalogue ───────────────
        rand = random.random()

        # Construire la roue de probabilité
        seuil_cumule = 0.0
        scenario_choisi = None

        for cle, sc in ANOMALIE_SCENARIOS.items():
            seuil_cumule += sc["probabilite"]
            if rand < seuil_cumule:
                scenario_choisi = (cle, sc)
                break

        # Si aucun scénario tiré → état normal
        if scenario_choisi is None:
            if self.anomalie_detectee:
                self._reset_anomalie_capteur()
                self._anomalie_type     = None
                self._anomalie_scenario = None
            return False

        cle_sc, sc = scenario_choisi

        # Générer la valeur du scénario
        valeur = sc["valeur_fn"]()
        description = sc["description_fn"](valeur)
        duree = random.randint(ANOMALIE_DUREE_MIN, ANOMALIE_DUREE_MAX)

        # Appliquer au capteur concerné
        self._appliquer_scenario(sc["type"], sc["niveau"], valeur)

        # Enregistrer état anomalie
        self.anomalie_detectee        = True
        self.description_anomalie     = description
        self._anomalie_type           = sc["type"]
        self._anomalie_scenario       = cle_sc
        self._anomalie_valeur         = valeur
        self._anomalie_steps_left     = duree

        print(f"  🔴 NOUVELLE anomalie [{cle_sc}] : {sc['type']} = {valeur} "
              f"| niveau : {sc['niveau']} | durée : {duree} steps = {duree * 30}s")
        print(f"  📝 → Écriture JSON immédiate pour garantir visibilité Agent")

        return True

    def _appliquer_scenario(self, type_anomalie: str, niveau: str, valeur: float):
        """Applique la valeur au bon capteur selon le type."""
        if type_anomalie == "temp":
            self.temperature_moteur_c      = valeur
            self.temperature_moteur_alerte = True

        elif type_anomalie == "pneu":
            self.pression_pneus_psi    = valeur
            self.pression_pneus_alerte = True

        elif type_anomalie == "freins":
            self.freins_usure_percent = valeur
            self.freins_defectueux    = (valeur > SEUIL_FREINS_ROUGE)

        elif type_anomalie == "batterie":
            self.batterie_percent = valeur
            self.batterie_faible  = True

        elif type_anomalie == "vibrations":
            self.vibrations_level     = valeur
            self.vibrations_anormales = True

        elif type_anomalie == "conso":
            self.consommation_l_100km = valeur
            self.consommation_elevee  = True

    def _reset_anomalie_capteur(self):
        """Remet le capteur de l'anomalie active à une valeur normale."""
        t = self._anomalie_type

        if t == "temp":
            progress = self.distance_covered_km / TOTAL_DISTANCE_KM
            self.temperature_moteur_c      = round(80.0 + progress * 10.0 + random.uniform(-2, 2), 1)
            self.temperature_moteur_alerte = False

        elif t == "pneu":
            self.pression_pneus_psi    = round(random.uniform(100.0, 115.0), 1)
            self.pression_pneus_alerte = False

        elif t == "freins":
            progress = self.distance_covered_km / TOTAL_DISTANCE_KM
            self.freins_usure_percent = round(10.0 + progress * 20.0 + random.uniform(-1, 1), 1)
            self.freins_defectueux    = False

        elif t == "batterie":
            self.batterie_percent = max(70.0, self.batterie_percent)
            self.batterie_faible  = False

        elif t == "vibrations":
            self.vibrations_level     = round(random.uniform(1.5, 5.0), 2)
            self.vibrations_anormales = False

        elif t == "conso":
            load_factor = 1.0 + (self.load_tonnes / 50.0) * 0.25
            self.consommation_l_100km = round(22.0 * load_factor + random.uniform(-1, 1), 1)
            self.consommation_elevee  = False

        self.anomalie_detectee    = False
        self.description_anomalie = "État normal - retour à la normale après alerte"

    # ── Vitesse réaliste ─────────────────────────────────────────
    def get_realistic_speed(self):
        if not self.is_engine_on or self.is_finished:
            return 0.0
        base = 60.0
        if self.temperature_moteur_alerte: base *= 0.70
        if self.freins_defectueux:         base *= 0.80
        if self.vibrations_anormales:      base *= 0.85
        if self.surcharge_niveau == "rouge":  base *= 0.80
        elif self.surcharge_niveau == "jaune": base *= 0.90
        return max(0.0, base + random.uniform(-3, 3))

    # ══════════════════════════════════════════════════════════════
    # MISE À JOUR DES CAPTEURS
    # ══════════════════════════════════════════════════════════════
    def update_sensors(self):
        if not self.is_engine_on:
            self.temperature_moteur_c = 25.0
            self.current_speed_kmh    = 0.0
            return

        progress = self.distance_covered_km / TOTAL_DISTANCE_KM
        load     = self.load_tonnes

        # Température
        if self._anomalie_type != "temp":
            base_temp = 80.0 + progress * 15.0 + max(0, load - 30.0) * 1.0
            self.temperature_moteur_c      = round(base_temp + random.uniform(-2, 2), 1)
            self.temperature_moteur_alerte = (self.temperature_moteur_c >= SEUIL_TEMP_JAUNE)

        # Pression pneus
        if self._anomalie_type != "pneu":
            base_pneu = 112.0 - max(0, load - 30.0) * 0.4 - progress * 4.0
            self.pression_pneus_psi    = round(base_pneu + random.uniform(-1.5, 1.5), 1)
            self.pression_pneus_alerte = (
                self.pression_pneus_psi < SEUIL_PNEU_JAUNE
                or self.pression_pneus_psi > SEUIL_PNEU_HAUT
            )

        # Consommation
        if self._anomalie_type != "conso":
            load_factor  = 1.0 + (load / 50.0) * 0.25
            speed_factor = 1.0 + (self.current_speed_kmh / 100.0) * 0.15
            self.consommation_l_100km = round(
                22.0 * load_factor * speed_factor + random.uniform(-1, 1), 1
            )
            self.consommation_elevee = (self.consommation_l_100km > SEUIL_CONSO_JAUNE)

        # Carburant restant
        rate = (self.consommation_l_100km / 100.0) * (self.current_speed_kmh / 3600.0)
        self.fuel_level_liters = max(0.0, round(self.fuel_level_liters - rate, 2))

        # Batterie
        if self._anomalie_type != "batterie":
            self.batterie_percent = max(0.0, round(self.batterie_percent - 0.001, 1))
            self.batterie_faible  = (self.batterie_percent < SEUIL_BATT_JAUNE)

        # Vibrations
        if self._anomalie_type != "vibrations":
            spd_vib = (self.current_speed_kmh / 100.0) * 2.5
            if self.freins_defectueux:     spd_vib *= 1.4
            if self.pression_pneus_alerte: spd_vib *= 1.25
            load_vib = max(0, load - 30.0) * 0.12
            self.vibrations_level     = round(2.0 + spd_vib + load_vib + random.uniform(-0.5, 0.5), 2)
            self.vibrations_anormales = (self.vibrations_level > SEUIL_VIB_JAUNE)

        # Freins
        if self._anomalie_type != "freins":
            self.freins_usure_percent = round(
                10.0 + progress * 20.0
                + max(0, load - 30.0) * 0.4
                + random.uniform(-0.5, 0.5), 1
            )
            self.freins_defectueux = (self.freins_usure_percent > SEUIL_FREINS_ROUGE)

    def calculate_elapsed_time(self):
        if self.is_engine_on:
            self.elapsed_sec = int(
                (datetime.now() - self.journey_start_time).total_seconds()
            )
        return self.elapsed_sec

    def step(self, time_delta_sec=30) -> bool:
        """Retourne True si une nouvelle anomalie a été créée."""
        if self.is_finished:
            return False

        if not self.is_engine_on and self.distance_covered_km == 0:
            self.start_engine()

        self.calculate_elapsed_time()
        self.timestamp         = datetime.now()
        self.current_speed_kmh = self.get_realistic_speed()
        self.distance_covered_km += (self.current_speed_kmh / 3600.0) * time_delta_sec

        if self.elapsed_sec > 0:
            self.avg_speed_kmh = round(
                (self.distance_covered_km / self.elapsed_sec) * 3600, 2
            )

        if self.distance_covered_km >= TOTAL_DISTANCE_KM:
            self.distance_covered_km  = TOTAL_DISTANCE_KM
            self.is_finished          = True
            self.is_engine_on         = False
            self.engine_status        = "Moteur arrêté"
            self.journey_status       = "Arrivée à Tétouan ✓"
            self.description_anomalie = "Trajet terminé avec succès !"
            self.current_speed_kmh    = 0.0
            return False

        # Ordre correct : charge → anomalies → capteurs
        self.update_load()
        nouvelle_anomalie = self.trigger_dynamic_anomalies()
        self.update_sensors()

        progress_percent  = (self.distance_covered_km / TOTAL_DISTANCE_KM) * 100
        self.journey_status = f"En cours : {progress_percent:.1f}% du trajet"

        return nouvelle_anomalie

    def to_dict(self):
        return {
            "truck_id":                    self.truck_id,
            "timestamp":                   self.timestamp.isoformat(),
            "journey_status":              self.journey_status,
            "engine_status":               self.engine_status,
            "position":                    self.get_position(),
            "distance_covered_km":         round(self.distance_covered_km, 2),
            "total_distance_km":           TOTAL_DISTANCE_KM,
            "progress_percent":            round((self.distance_covered_km / TOTAL_DISTANCE_KM) * 100, 1),
            "current_speed_kmh":           round(self.current_speed_kmh, 2),
            "avg_speed_kmh":               self.avg_speed_kmh,
            "elapsed_time_sec":            self.elapsed_sec,
            "elapsed_time_formatted":      self.format_time(self.elapsed_sec),
            "estimated_arrival_time":      self.calculate_eta(),
            "load_tonnes":                 self.load_tonnes,
            "charge_max_autorisee_tonnes": CHARGE_MAX_TONNES,
            "surcharge_active":            self.load_tonnes > CHARGE_MAX_TONNES,
            "surcharge_niveau":            self.surcharge_niveau,
            "charge_seuil_jaune":          SEUIL_CHARGE_JAUNE,
            "charge_seuil_rouge":          SEUIL_CHARGE_ROUGE,
            "fuel_level_liters":           round(self.fuel_level_liters, 2),

            # ⬇️  Clés renommées pour correspondre à la table thresholds ⬇️
            "consommation_carburant":      round(self.consommation_l_100km, 2),
            "temperature_moteur":          round(self.temperature_moteur_c, 1),
            "pression_pneus":              round(self.pression_pneus_psi, 1),
            "etat_batterie":               round(self.batterie_percent, 1),
            "niveaux_vibration":           round(self.vibrations_level, 2),

            "freins_usure_percent":        round(self.freins_usure_percent, 1),

            "temperature_moteur_alerte":   self.temperature_moteur_alerte,
            "pression_pneus_alerte":       self.pression_pneus_alerte,
            "consommation_elevee":         self.consommation_elevee,
            "batterie_faible":             self.batterie_faible,
            "vibrations_anormales":        self.vibrations_anormales,
            "freins_defectueux":           self.freins_defectueux,
            "anomalie_detectee":           self.anomalie_detectee,
            "anomalie_type_actif":         self._anomalie_type,
            "anomalie_scenario_actif":     self._anomalie_scenario,   # ← nouveau : nom du scénario
            "anomalie_steps_restants":     self._anomalie_steps_left,
            "description_anomalie":        self.description_anomalie,
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
        remaining = TOTAL_DISTANCE_KM - self.distance_covered_km
        eta = datetime.now() + timedelta(hours=remaining / self.current_speed_kmh)
        return eta.strftime("%H:%M:%S")


# ===== État global =====
truck_state = TruckState()


def ecrire_json():
    """Écrit le JSON avec informations de debug améliorées."""
    try:
        os.makedirs(os.path.dirname(JSON_FILE_PATH), exist_ok=True)
        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(truck_state.to_dict(), f, indent=2, ensure_ascii=False)

        niveau_emoji = {"none": "🟢", "jaune": "🟡", "rouge": "🔴"}
        emoji = niveau_emoji.get(truck_state.surcharge_niveau, "⚪")

        anomalie_info = ""
        if truck_state._anomalie_type:
            anomalie_info = (
                f"| 🔴 [{truck_state._anomalie_scenario}] "
                f"({truck_state._anomalie_steps_left} steps = "
                f"{truck_state._anomalie_steps_left * 30}s)"
            )

        print(
            f"✅ [{datetime.now().strftime('%H:%M:%S')}] JSON mis à jour "
            f"| {emoji} Charge : {truck_state.load_tonnes} T "
            f"| Temp : {truck_state.temperature_moteur_c}°C "
            f"| Freins : {truck_state.freins_usure_percent}% "
            f"{anomalie_info}"
        )
    except Exception as e:
        print(f"❌ Erreur écriture JSON : {e}")


async def background_simulation():
    """Boucle principale avec écriture immédiate lors d'une nouvelle anomalie."""
    steps_depuis_ecriture = 0
    steps_par_ecriture    = WRITE_INTERVAL_SEC // UPDATE_INTERVAL_SEC

    while True:
        try:
            nouvelle_anomalie = truck_state.step(time_delta_sec=UPDATE_INTERVAL_SEC)
            steps_depuis_ecriture += 1

            if nouvelle_anomalie:
                print("  ⚡ ÉCRITURE JSON IMMÉDIATE (nouvelle anomalie détectée)")
                ecrire_json()
                steps_depuis_ecriture = 0

            elif steps_depuis_ecriture >= steps_par_ecriture:
                ecrire_json()
                steps_depuis_ecriture = 0

            if truck_state.is_finished:
                print("✓ Trajet terminé ! Redémarrage dans 10 s...")
                await asyncio.sleep(10)
                truck_state.reset_journey()
                print("🚀 Nouveau trajet démarré !")

            await asyncio.sleep(UPDATE_INTERVAL_SEC)

        except Exception as e:
            print(f"❌ Erreur simulation : {e}")
            await asyncio.sleep(5)


STATIC_DIR = os.path.dirname(os.path.abspath(__file__))


@app.get("/")
async def serve_dashboard():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.on_event("startup")
async def startup_event():
    total_proba = sum(sc["probabilite"] for sc in ANOMALIE_SCENARIOS.values())

    print("=" * 80)
    print("🚛  TruckMind — Simulation Réaliste Volvo FH  (main.py v4)")
    print("=" * 80)
    print(f"📍 Trajet       : Tanger → Tétouan ({TOTAL_DISTANCE_KM} km)")
    print(f"📁 JSON         : {JSON_FILE_PATH}")
    print(f"🔄 Écriture     : toutes les {WRITE_INTERVAL_SEC} s + IMMÉDIATE si anomalie")
    print("")
    print("📊 SCÉNARIOS DE CHARGE :")
    print("   🟢 70% → Charge normale (25-29 T)")
    print("   🟡 20% → Surcharge modérée (31-37 T)")
    print("   🔴  8% → Surcharge critique (38-42 T)")
    print("   🔴  2% → Urgence (43-48 T)")
    print("")
    print(f"🚨 CATALOGUE D'ANOMALIES ({len(ANOMALIE_SCENARIOS)} scénarios | "
          f"proba totale : {total_proba*100:.1f}% par step)")
    print("")

    categories = {}
    for cle, sc in ANOMALIE_SCENARIOS.items():
        t = sc["type"]
        categories.setdefault(t, []).append((cle, sc))

    icones = {
        "temp":      "🌡️ TEMPÉRATURE MOTEUR",
        "pneu":      "🛞 PRESSION PNEUS",
        "freins":    "🛑 FREINS",
        "batterie":  "🔋 BATTERIE",
        "vibrations":"📳 VIBRATIONS",
        "conso":     "⛽ CONSOMMATION",
    }

    for type_key, scenarios in categories.items():
        print(f"  {icones.get(type_key, type_key)} :")
        for cle, sc in scenarios:
            print(f"      [{sc['niveau'].upper():5s}] {sc['probabilite']*100:.1f}% → {cle}")
        print("")

    print(f"🔁 Durée anomalie : {ANOMALIE_DUREE_MIN}–{ANOMALIE_DUREE_MAX} steps "
          f"({ANOMALIE_DUREE_MIN*30}–{ANOMALIE_DUREE_MAX*30} s)")
    print("   📝 Écriture JSON IMMÉDIATE à chaque nouvelle anomalie")
    print("")
    print("🌐 Dashboard   : http://localhost:8000/")
    print("=" * 80)
    asyncio.create_task(background_simulation())


async def event_generator():
    last_ts = None
    yield f"data: {json.dumps(truck_state.to_dict(), ensure_ascii=False)}\n\n"
    last_ts = truck_state.timestamp
    while True:
        try:
            if truck_state.timestamp != last_ts:
                last_ts = truck_state.timestamp
                yield f"data: {json.dumps(truck_state.to_dict(), ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ Erreur SSE : {e}")
            break


@app.get("/stream")
async def stream_data():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/data")
async def get_current_data():
    return truck_state.to_dict()


@app.get("/status")
async def get_status():
    return {
        "truck_id":             truck_state.truck_id,
        "status":               truck_state.journey_status,
        "position":             truck_state.get_position(),
        "progress":             round((truck_state.distance_covered_km / TOTAL_DISTANCE_KM) * 100, 1),
        "current_speed":        round(truck_state.current_speed_kmh, 2),
        "load_tonnes":          truck_state.load_tonnes,
        "surcharge":            truck_state.load_tonnes > CHARGE_MAX_TONNES,
        "anomalie_active":      truck_state._anomalie_type,
        "anomalie_scenario":    truck_state._anomalie_scenario,
        "anomalie_steps_left":  truck_state._anomalie_steps_left,
        "is_finished":          truck_state.is_finished,
    }


@app.get("/reset")
async def reset_journey():
    truck_state.reset_journey()
    return {"message": "Trajet redémarré", "status": "Prêt à démarrer"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="localhost", port=8000, reload=True)