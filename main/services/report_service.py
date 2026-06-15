from datetime import datetime

def generate_trip_report_html(history_data: list) -> str:
    if not history_data:
        return "<h2>Aucune donnee de trajet disponible pour generer un rapport.</h2>"

    # Recuperer un ID de camion (par defaut ou depuis 'donnees_camion' si present)
    truck_id = "Volvo FH"
    for entry in history_data:
        if "truck_id" in entry:
            truck_id = entry["truck_id"]
            break
        elif "donnees_camion" in entry and isinstance(entry["donnees_camion"], dict):
            truck_id = entry["donnees_camion"].get("truck_id", "Volvo FH")
            break

    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    total_alerts = len(history_data)
    critical_alerts = sum(1 for e in history_data if e.get("severite") == "CRITIQUE")

    rows = ""
    for entry in history_data:
        ts = entry.get("timestamp", "")
        if "T" in ts:
            time_str = ts.split("T")[1][:8]
        else:
            time_str = ts[:8] if len(ts) >= 8 else ""

        sev = entry.get("severite", "NORMAL")
        color = "#e74c3c" if sev == "CRITIQUE" else "#f1c40f" if sev == "ATTENTION" else "#2ecc71"

        rows += f"""
        <tr>
            <td>{entry.get("cycle", "")}</td>
            <td>{time_str}</td>
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
            <div class="logo">TruckMind Report</div>
            <div>
                <strong>Vehicule :</strong> {truck_id}<br>
                <strong>Date :</strong> {date_str}
            </div>
        </div>
        <div class="summary-cards">
            <div class="card"><div class="val">{len(history_data)}</div><div>Cycles Analyses</div></div>
            <div class="card"><div class="val">{total_alerts}</div><div>Alertes Totales</div></div>
            <div class="card"><div class="val" style="color: #e74c3c;">{critical_alerts}</div><div>Incidents Critiques</div></div>
        </div>
        <h3>Historique des evenements</h3>
        <table>
            <thead><tr><th>Cycle</th><th>Heure</th><th>Severite</th><th>Evenement</th><th>Statut Recommande</th><th>Action vitesse</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        <button class="btn-print" onclick="window.print()">Imprimer en PDF</button>
    </body>
    </html>
    """
    return html