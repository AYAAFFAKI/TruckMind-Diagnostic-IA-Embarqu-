from datetime import datetime
import json

def generate_trip_report_html(history_data: list) -> str:
    if not history_data:
        return "<h2>Aucune donnée de trajet disponible pour générer un rapport.</h2>"
        
    last_entry = history_data[-1]
    truck_id = last_entry.get("capteurs", {}).get("truck_id", "Volvo_FH_001")
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    total_alerts = sum(1 for entry in history_data if entry.get("alertes"))
    critical_alerts = sum(1 for entry in history_data if entry.get("severite") == "CRITIQUE")
    
    rows = ""
    for entry in history_data:
        t = entry.get("timestamp", "").split("T")[-1][:8]
        sev = entry.get("severite", "NORMAL")
        color = "#e74c3c" if sev == "CRITIQUE" else "#f1c40f" if sev == "ATTENTION" else "#2ecc71"
        rows += f"""
        <tr>
            <td>{entry.get("cycle")}</td>
            <td>{t}</td>
            <td style="color: {color}; font-weight: bold;">{sev}</td>
            <td>{entry.get("titre", "Normal")}</td>
            <td>{entry.get("statut_final", "CONTINUER")}</td>
            <td>{entry.get("action_vitesse", "")}</td>
        </tr>
        """
        
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Rapport de Trajet - {truck_id}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; }}
            .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #2c3e50; padding-bottom: 20px; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
            .summary-cards {{ display: flex; gap: 20px; margin-top: 30px; }}
            .card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; flex: 1; text-align: center; border: 1px solid #e9ecef; }}
            .card .val {{ font-size: 32px; font-weight: bold; color: #2980b9; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 40px; font-size: 14px; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #2c3e50; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
            .btn-print {{ display: block; width: 200px; margin: 30px auto; padding: 10px; text-align: center; background: #2980b9; color: white; text-decoration: none; border-radius: 5px; cursor: pointer; border: none; font-size: 16px; }}
            @media print {{ .btn-print {{ display: none; }} body {{ margin: 0; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🚛 TruckMind Report</div>
            <div>
                <strong>Véhicule :</strong> {truck_id}<br>
                <strong>Date :</strong> {date_str}
            </div>
        </div>
        
        <div class="summary-cards">
            <div class="card">
                <div class="val">{len(history_data)}</div>
                <div>Cycles Analysés</div>
            </div>
            <div class="card">
                <div class="val">{total_alerts}</div>
                <div>Alertes Totales</div>
            </div>
            <div class="card">
                <div class="val" style="color: #e74c3c;">{critical_alerts}</div>
                <div>Incidents Critiques</div>
            </div>
        </div>
        
        <h3>Historique des événements</h3>
        <table>
            <thead>
                <tr>
                    <th>Cycle</th>
                    <th>Heure</th>
                    <th>Sévérité</th>
                    <th>Événement</th>
                    <th>Statut Recommandé</th>
                    <th>Vitesse</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        
        <button class="btn-print" onclick="window.print()">🖨️ Imprimer en PDF</button>
    </body>
    </html>
    """
    return html
