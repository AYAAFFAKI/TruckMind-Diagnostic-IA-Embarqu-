# TruckMind — Intelligence Embarquée Camion Volvo FH/FM

TruckMind est un système de diagnostic embarqué (Diagnostic IA Embarqué) spécialement conçu pour les camions Volvo FH/FM. Le système s'appuie sur la technologie RAG (Retrieval-Augmented Generation) pour fusionner des données structurées (SQL) issues des capteurs et des journaux de maintenance, avec des données non structurées (ChromaDB) provenant des manuels techniques, afin de fournir des analyses précises via un puissant moteur d'intelligence artificielle.

**Auteure :** AYA AFFAKI  
**Établissement :** École Supérieure de Technologie de Tétouan (ESTT)  
**Entreprise d'accueil (Stage) :** Smart Automation Technologies  
**Filière :** Intelligence Artificielle (DUT 2025-2026)

## 🚀 Fonctionnalités Principales
- **Agent Intelligent (LangGraph Agent) :** Un routeur intelligent qui classifie automatiquement les requêtes (statistiques, codes d'erreur, questions générales) et les redirige vers des recherches SQL ou des recherches vectorielles dans des documents PDF.
- **Tableau de Bord de la Flotte (Dashboard) :** Une interface utilisateur interactive pour suivre l'état des camions, les freins, la qualité de l'huile et prévoir les risques (Predictive Score).
- **Recherche de Codes d'Erreur (DTC Search) :** Une base de données contenant des milliers de codes (OBD-II) pour diagnostiquer les problèmes et proposer des recommandations.
- **Système d'Alertes Dynamique :** Des alertes en temps réel basées sur le dépassement de seuils critiques (Température du moteur, Pression des pneus, etc.).

## 🛠️ Technologies Utilisées
- **Backend :** Python, Flask
- **Bases de données :** SQLite (pour la maintenance et les alertes), ChromaDB (pour la recherche vectorielle)
- **Intelligence Artificielle :** LangGraph, LangChain, Groq API (Qwen3-32b), Sentence Transformers
- **Frontend :** HTML, CSS, JavaScript (Vanilla JS pour de meilleures performances)

## 📁 Structure du Projet
```text
truck_rag_sys/
│
├── main/                   # Dossier principal de l'application
│   ├── app.py              # Serveur principal (Flask + LangGraph + APIs)
│   ├── static/             # Fichiers statiques (style.css, main.js)
│   ├── templates/          # Templates HTML (index.html)
│   ├── knowledge/          # Bases de données SQLite
│   └── data/               # Base de données vectorielle ChromaDB
│
├── uploads/                # Manuels et documents techniques (PDF)
├── test/                   # Fichiers de test et données expérimentales
├── .env                    # Variables d'environnement et clés API
├── requerments.txt         # Liste des dépendances requises
└── read.md                 # Ce fichier de documentation
```

## ⚙️ Installation et Exécution

1. **Installer les dépendances :**
   Assurez-vous d'être dans le répertoire racine du projet et exécutez la commande suivante :
   ```bash
   pip install -r requerments.txt
   ```

2. **Configurer les variables d'environnement :**
   Vérifiez que le fichier `.env` est configuré avec votre clé `GROQ_API_KEY`, et que les chemins vers le dossier `CHROMA_DIR` et les fichiers PDF sont corrects.

3. **Lancer le serveur :**
   Démarrez l'application Flask via la commande suivante :
   ```bash
   python main/app.py
   ```
   *(Ou via `flask run` si l'environnement Flask est configuré).*

4. **Accéder à l'interface :**
   Ouvrez votre navigateur web à l'adresse locale : `http://127.0.0.1:5000` (ou `http://localhost:5000`).

---
*Ce projet académique a été conçu et développé dans le cadre d'un stage chez Smart Automation Technologies, axé sur les applications de l'IA pour le diagnostic proactif dans le secteur du transport.*
