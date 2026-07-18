# TruckMind — Intelligence Embarquée Camion Volvo FH/FM

<div align="center">

![TruckMind Logo](https://img.shields.io/badge/TruckMind-Diagnostic%20IA-blue)
![Python](https://img.shields.io/badge/Python-3.8+-green)
![Flask](https://img.shields.io/badge/Flask-2.0+-red)
![License](https://img.shields.io/badge/License-Academic-orange)

**Système de Diagnostic Embarqué par Intelligence Artificielle pour Camions Volvo FH/FM**

</div>

---

## ⚠️ Statut du Projet / حالة المشروع

**Ce projet a été développé dans le cadre d'un projet académique (stage). Toute modification ou mise à jour effectuée après le 18/07/2026 ne fait pas partie du projet académique initial, mais résulte de la décision de l'auteure de poursuivre le développement du projet en dehors de ce cadre.**

---

##  Description

TruckMind est un système de diagnostic embarqué (Diagnostic IA Embarqué) spécialement conçu pour les camions Volvo FH/FM. Le système s'appuie sur la technologie **RAG (Retrieval-Augmented Generation)** pour fusionner des données structurées (SQL) issues des capteurs et des journaux de maintenance, avec des données non structurées (ChromaDB) provenant des manuels techniques, afin de fournir des analyses précises via un puissant moteur d'intelligence artificielle.

###  Objectifs Principaux

- **Diagnostic Proactif :** Anticiper les pannes avant qu'elles ne surviennent grâce à l'analyse prédictive
- **Maintenance Intelligente :** Optimiser les interventions de maintenance en fonction de l'état réel des véhicules
- **Sécurité Renforcée :** Alerte en temps réel en cas de dépassement de seuils critiques
- **Réduction des Coûts :** Minimiser les temps d'arrêt et les coûts de maintenance

---

##  Auteur

**Auteure :** AYA AFFAKI  
**Établissement :** École Supérieure de Technologie de Tétouan (ESTT)  
**Entreprise d'accueil (Stage) :** Smart Automation Technologies  
**Filière :** Intelligence Artificielle (DUT 2025-2026)

---

##  Fonctionnalités Principales

###  Agent Intelligent (LangGraph Agent)
- **Routeur Intelligent :** Classifie automatiquement les requêtes (statistiques, codes d'erreur, questions générales)
- **Recherche Multi-Sources :** Redirige vers des recherches SQL ou vectorielles dans les documents PDF
- **Pipeline RAG Avancé :** Fusionne les données structurées et non structurées pour des réponses précises

###  Tableau de Bord de la Flotte (Dashboard)
- **Suivi en Temps Réel :** Interface interactive pour suivre l'état des camions
- **Indicateurs Clés :** État des freins, qualité de l'huile, température moteur
- **Score Prédictif :** Prévision des risques basée sur l'historique de maintenance
- **Visualisation des Alertes :** Affichage des alertes actives (ROUGE/JAUNE/VERT)

###  Recherche de Codes d'Erreur (DTC Search)
- **Base de Données Complète :** Plus de 3 000 codes OBD-II
- **Diagnostic Précis :** Identification des symptômes, systèmes, pièces et gravité
- **Recommandations :** Actions techniques suggérées pour chaque code

###  Système d'Alertes Dynamique
- **Alertes en Temps Réel :** Basées sur le dépassement de seuils critiques
- **Seuils Configurables :** Température moteur, pression pneus, qualité huile, batterie, etc.
- **Niveaux de Gravité :** ROUGE (critique), JAUNE (attention), VERT (normal)
- **Actions Recommandées :** Instructions spécifiques pour chaque type d'alerte

###  Historique des Conversations
- **Persistance des Données :** Sauvegarde de l'historique des conversations
- **Contexte Maintenu :** Amélioration des réponses grâce à l'historique
- **Analyse des Tendances :** Suivi de l'évolution des problèmes

###  Simulateur de Camion
- **Simulation de Scénarios :** Test du système avec des données simulées
- **Génération de Données :** Création de trajets avec différents paramètres
- **Validation des Alertes :** Vérification du système d'alertes en conditions contrôlées

---

##  Technologies Utilisées

### Backend
- **Python 3.8+** : Langage principal
- **Flask 2.0+** : Framework web pour l'API REST
- **SQLite** : Base de données relationnelle pour la maintenance et les alertes
- **ChromaDB** : Base de données vectorielle pour la recherche sémantique

### Intelligence Artificielle
- **LangGraph** : Framework pour les agents IA
- **LangChain** : Framework pour les applications LLM
- **Groq API (Qwen3-32b)** : Modèle de langage pour les réponses
- **Sentence Transformers** : Modèles d'embeddings multilingues
- **HuggingFace** : Hub pour les modèles pré-entraînés

### Frontend
- **HTML5** : Structure des pages
- **CSS3** : Style et mise en page
- **JavaScript (Vanilla)** : Logique interactive et appels API

### Sécurité
- **Flask-CORS** : Gestion des requêtes cross-origin
- **Flask-Limiter** : Limitation du taux de requêtes
- **python-dotenv** : Gestion sécurisée des variables d'environnement

---

##  Structure du Projet

```text
truck_rag_sys/
│
├── main/                           # Dossier principal de l'application
│   ├── app.py                      # Serveur principal (Flask + LangGraph + APIs)
│   ├── static/                     # Fichiers statiques
│   │   ├── style.css              # Styles CSS
│   │   ├── main.js                # Logique JavaScript
│   │   └── ...                    # Autres assets
│   ├── templates/                  # Templates HTML
│   │   ├── index.html             # Page principale
│   │   ├── notifications.html     # Page des notifications
│   │   └── simulator.html         # Page du simulateur
│   ├── knowledge/                  # Bases de données SQLite
│   │   ├── truck_diagnostic.db   # Base de données principale
│   │   └── setup_db.py           # Script d'initialisation
│   ├── data/                       # Base de données vectorielle ChromaDB
│   ├── services/                   # Services métier
│   │   ├── history_service.py     # Gestion de l'historique
│   │   ├── notification_service.py # Service de notifications
│   │   └── simulator_service.py   # Service de simulation
│   └── logs/                       # Logs de l'application
│
├── test/                           # Fichiers de test et données expérimentales
│   ├── knowledge/                  # Tests de la base de connaissances
│   ├── simulateur/                 # Tests du simulateur
│   ├── evolution/                  # Données d'évolution
│   └── truck_diagnostic_evaluation.ipynb  # Notebook d'évaluation
│
├── uploads/                        # Manuels et documents techniques (PDF)
│   └── rapport_Manuel.pdf         # Manuel technique Volvo
│
├── uploads_sans_clean/             # Données brutes (non nettoyées)
│
├── .env                            # Variables d'environnement (NE PAS COMMITTER)
├── .gitignore                      # Fichiers ignorés par Git
├── requirements.txt                # Liste des dépendances requises
├── README.md                       # Ce fichier de documentation
```

---

##  Installation et Exécution

### Prérequis

- Python 3.8 ou supérieur
- pip (gestionnaire de paquets Python)
- Accès internet (pour l'API Groq et le téléchargement des modèles)

### 1. Cloner le Repository

```bash
git clone <repository-url>
cd truck_rag_sys
```

### 2. Installer les Dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer les Variables d'Environnement


Éditez le fichier `.env` et ajoutez vos configurations :

```bash
# Clé API Groq (obligatoire)
GROQ_API_KEY=votre_cle_api_ici

# Modèle LLM
LLM_MODEL=qwen/qwen3-32b

# Chemins des fichiers
CHROMA_DIR=./main/data
PDF_FILES=./uploads/rapport_Manuel.pdf

# Configuration Flask
PORT=5000
FLASK_DEBUG=0

# Chemins des fichiers d'historique (données sensibles)
CONVERSATIONS_HISTORY_PATH=./main/conversations_history.json
TRUCK_HISTORY_PATH=./main/services/truck_history.json
NOTIFICATIONS_RAM_PATH=./main/services/notifications_ram.json
```

** IMPORTANT :** Obtenez votre clé API Groq gratuitement sur : https://console.groq.com/keys

### 4. Initialiser la Base de Données

```bash
python main/knowledge/setup_db.py
```

### 5. Lancer le Serveur

```bash
python main/app.py
```

Ou via Flask :

```bash
flask run
```

### 6. Accéder à l'Interface

Ouvrez votre navigateur web à l'adresse : `http://127.0.0.1:5000`

---

## Utilisation

### Interface Principale

1. **Chat IA :** Posez des questions sur l'état des camions, les codes d'erreur, ou demandez des conseils de maintenance
2. **Dashboard :** Visualisez l'état de la flotte, les alertes actives et les statistiques
3. **Notifications :** Consultez l'historique des notifications et des alertes
4. **Simulateur :** Testez le système avec des données simulées

### Exemples de Requêtes

- "Quel est l'état du camion V0001 ?"
- "Que signifie le code d'erreur P0301 ?"
- "Combien de camions ont des freins défectueux ?"
- "Quelle est la température moyenne du moteur ?"
- "Liste des alertes critiques actives"

### API Endpoints

- `GET /` : Interface principale
- `POST /api/chat` : Chat avec l'IA
- `GET /api/status` : Statut du système
- `GET /api/fleet/stats` : Statistiques de la flotte
- `GET /api/fleet/alerts` : Alertes actives
- `GET /api/vehicle/<id>` : Données d'un véhicule spécifique
- `GET /api/dtc/<code>` : Diagnostic d'un code DTC
- `GET /api/knowledge/search` : Recherche dans la base de connaissances

---

##  Sécurité et Confidentialité

### Variables d'Environnement

Toutes les informations sensibles sont stockées dans le fichier `.env` qui est **ignoré par Git** (voir `.gitignore`).

### Fichiers Protégés

Les fichiers suivants contiennent des données sensibles et ne sont pas versionnés :
- `main/conversations_history.json` : Historique des conversations
- `main/services/truck_history.json` : Historique des camions
- `main/services/notifications_ram.json` : Notifications temporaires

### Mesures de Sécurité

- **Rate Limiting :** Protection contre les abus d'API
- **CORS :** Restriction des origines autorisées
- **Security Headers :** En-têtes de sécurité HTTP
- **Validation des Entrées :** Vérification des données utilisateur

---

##  Tests et Évaluation

### Exécuter les Tests

```bash
python test/knowledge/truck_diagnostic.py
```

### Notebook d'Évaluation

Le notebook `test/truck_diagnostic_evaluation.ipynb` contient des évaluations détaillées du système.

---

##  Contribution

Ce projet est un projet académique. Pour toute question ou suggestion, veuillez contacter l'auteure.

---

##  Licence

Ce projet est développé dans un cadre académique. Veuillez contacter l'auteure pour toute utilisation commerciale.

---

##  Remerciements

- **Smart Automation Technologies** : Entreprise d'accueil pour le stage
- **École Supérieure de Technologie de Tétouan (ESTT)** : Établissement de formation
- **Groq** : Pour l'API LLM performante
- **Volvo** : Pour la documentation technique

---

##  Contact

**Aya Affaki**  
Étudiante en Intelligence Artificielle (DUT 2025-2026)  
École Supérieure de Technologie de Tétouan

---

<div align="center">

*Ce projet académique a été conçu et développé dans le cadre d'un stage chez Smart Automation Technologies, axé sur les applications de l'IA pour le diagnostic proactif dans le secteur du transport.*

** TruckMind — L'Intelligence au Service du Transport Intelligent **

</div>
