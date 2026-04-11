from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import sqlite3
import os
from datetime import datetime
import traceback

def generate_pdf_report(report_id, output_path=None):
    """Generate PDF report for given report_id"""
    try:
        if output_path is None:
            # Ensure static directory exists
            os.makedirs('static', exist_ok=True)
            output_path = f"static/report_{report_id}.pdf"
        
        # Fetch report data
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT r.overall_risk_score, r.risk_level, p.name, r.created_date, r.diagnosis,
                   r.recommendation, r.interpretation
            FROM reports r
            JOIN patients p ON r.patient_id = p.patient_id
            WHERE r.report_id = ?
        """, (report_id,))
        
        report_data = cursor.fetchone()
        
        if not report_data:
            conn.close()
            print(f"❌ Report {report_id} not found for PDF generation")
            return None
        
        risk_score, risk_level, patient_name, created_date, diagnosis, recommendation, interpretation_json = report_data
        
        # Get test results
        cursor.execute("""
            SELECT parameter_name, parameter_value, unit, reference_range, flag
            FROM test_results tr
            JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
            WHERE pt.patient_id = (SELECT patient_id FROM reports WHERE report_id = ?)
            ORDER BY parameter_name
        """, (report_id,))
        
        test_results = cursor.fetchall()
        conn.close()
        
        # Create PDF
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            alignment=TA_CENTER,
            spaceAfter=30,
            textColor=colors.HexColor('#2c3e50')
        )
        story.append(Paragraph("Medical Laboratory Report", title_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Report Info
        info_data = [
            ["Report ID:", f"#{report_id}"],
            ["Patient Name:", patient_name],
            ["Report Date:", created_date[:10] if created_date else datetime.now().strftime('%Y-%m-%d')],
            ["Risk Score:", f"{risk_score} ({risk_level})"],
            ["Diagnosis Status:", diagnosis if diagnosis else "Pending Review"]
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 12),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#7f8c8d')),
            ('TEXTCOLOR', (1,0), (1,-1), colors.HexColor('#2c3e50')),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Test Results
        story.append(Paragraph("Test Results", styles['Heading2']))
        story.append(Spacer(1, 0.1*inch))
        
        test_data = [["Parameter", "Value", "Unit", "Reference Range", "Status"]]
        for test in test_results:
            test_data.append([
                test[0].replace('_', ' ').title(), 
                str(test[1]), 
                test[2] if test[2] else "-",
                test[3] if test[3] else "Standard",
                test[4] if test[4] else "Normal"
            ])
        
        test_table = Table(test_data, colWidths=[2*inch, 1*inch, 1*inch, 1.5*inch, 1.5*inch])
        
        # Style the table
        table_style = [
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#ecf0f1')),
            ('FONTSIZE', (0,1), (-1,-1), 10),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
        ]
        
        # Add color coding for status column
        for i, row in enumerate(test_data[1:], start=1):
            if row[4] and 'Critical' in row[4]:
                table_style.append(('TEXTCOLOR', (4,i), (4,i), colors.red))
                table_style.append(('FONTNAME', (4,i), (4,i), 'Helvetica-Bold'))
            elif row[4] and ('High' in row[4] or 'Low' in row[4]):
                table_style.append(('TEXTCOLOR', (4,i), (4,i), colors.orange))
        
        test_table.setStyle(TableStyle(table_style))
        story.append(test_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Recommendation
        if recommendation:
            story.append(Paragraph("Clinical Recommendation", styles['Heading2']))
            story.append(Spacer(1, 0.1*inch))
            rec_style = ParagraphStyle(
                'Recommendation',
                parent=styles['Normal'],
                fontSize=12,
                spaceAfter=20,
                leftIndent=20,
                rightIndent=20,
                textColor=colors.HexColor('#2c3e50')
            )
            story.append(Paragraph(recommendation, rec_style))
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            alignment=TA_CENTER,
            textColor=colors.grey,
            spaceBefore=30
        )
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph("This is a computer-generated report. For verification, scan the QR code or use the hash verification system.", footer_style))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", footer_style))
        
        # Build PDF
        doc.build(story)
        print(f"✅ PDF generated successfully: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"❌ Error generating PDF: {str(e)}")
        traceback.print_exc()
        return None