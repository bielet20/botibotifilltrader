import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

class ReportingEngine:
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_json_report(self, trades_data: list, performance_metrics: dict) -> dict:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "metrics": performance_metrics,
            "trades": trades_data
        }

    def generate_pdf_report(self, filename: str, trades_data: list, performance_metrics: dict):
        doc = SimpleDocTemplate(os.path.join(self.output_dir, filename), pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        elements.append(Paragraph("ANTIGRAVITY Institutional Trading Report", styles['Title']))
        elements.append(Spacer(1, 12))

        # Metrics Section
        elements.append(Paragraph("Performance Overview", styles['Heading2']))
        metrics_data = [[k, v] for k, v in performance_metrics.items()]
        t_metrics = Table(metrics_data)
        t_metrics.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(t_metrics)
        elements.append(Spacer(1, 24))

        # Trades Section
        elements.append(Paragraph("Recent Activity", styles['Heading2']))
        trade_headers = ["Time", "Symbol", "Side", "Price", "Amount"]
        trade_rows = [trade_headers]
        for t in trades_data[:20]: # Limit to top 20 for readability
            trade_rows.append([
                t.time.strftime("%H:%M:%S") if hasattr(t, 'time') else "N/A",
                t.symbol,
                t.side.upper(),
                str(t.price),
                str(t.amount)
            ])
        
        t_trades = Table(trade_rows)
        t_trades.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.blue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        elements.append(t_trades)

        doc.build(elements)
        return os.path.join(self.output_dir, filename)

def calculate_metrics(trades: list) -> dict:
    # A simple metrics calculator
    if not trades:
        return {"total_trades": 0, "win_rate": "0%", "total_pnl": "$0"}
    
    buys = len([t for t in trades if t.side == 'buy'])
    sells = len([t for t in trades if t.side == 'sell'])
    
    return {
        "total_trades": len(trades),
        "total_buy_volume": sum(t.amount for t in trades if t.side == 'buy'),
        "total_sell_volume": sum(t.amount for t in trades if t.side == 'sell'),
        "report_period": datetime.now().strftime("%Y-%m-%d")
    }
